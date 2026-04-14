"""
base_client.py — HTTP client مع Retry وLogging لـ Tawseel API
Thread-safe session with automatic auth headers, exponential backoff, and
structured error handling.

Response format (all 3scale endpoints):
    { "data": {...}, "errorCodes": [0], "status": true }
"""

from __future__ import annotations

import logging
import time
from typing import Any

import requests
from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry

from .config import (
    BACKOFF_FACTOR,
    MAX_RETRIES,
    TIMEOUT_SECONDS,
    get_base_url,
    get_headers,
)
from .exceptions import TawseelException

logger = logging.getLogger("tawseel")


def _configure_session() -> requests.Session:
    """Build a Session with connection pooling and transport-level retries."""
    session = requests.Session()
    # Retry only on network/5xx failures — NOT on 4xx (those are API logic errors).
    retry = Retry(
        total=MAX_RETRIES,
        backoff_factor=BACKOFF_FACTOR,
        status_forcelist=[500, 502, 503, 504],
        allowed_methods=["GET", "POST", "PUT"],
        raise_on_status=False,
    )
    adapter = HTTPAdapter(max_retries=retry)
    session.mount("https://", adapter)
    session.mount("http://", adapter)
    return session


class TawseelClient:
    """
    Low-level HTTP wrapper for the Tawseel / Logisti REST API.

    All API responses use the envelope:
        { "data": <payload>, "errorCodes": [<int>], "status": <bool> }

    errorCodes == [0] and status == true  → success, returns data field
    status == false or errorCodes != [0]  → raises TawseelException

    Usage::

        client = TawseelClient()
        regions = client.get("/external/api/lookup/regions-list")
        result  = client.post("/external/api/driver/create", payload={...})
    """

    def __init__(self) -> None:
        self._session = _configure_session()
        self._base_url = get_base_url().rstrip("/")

    # ── Public helpers ──────────────────────────────────────────────────────────

    def get(self, path: str, params: dict | None = None) -> Any:
        """Send GET request and return parsed response body (data field)."""
        return self._request("GET", path, params=params)

    def post(self, path: str, payload: dict | None = None) -> Any:
        """Send POST request with JSON body and return parsed response body."""
        return self._request("POST", path, json=payload)

    def post_multipart(self, path: str, files: dict, data: dict | None = None) -> Any:
        """Send multipart/form-data POST (used by Recovery file upload)."""
        url = f"{self._base_url}{path}"
        # Remove Content-Type — requests sets it automatically for multipart
        headers = {k: v for k, v in get_headers().items() if k != "Content-Type"}
        logger.debug("POST (multipart) → %s", url)
        t0 = time.perf_counter()
        try:
            resp = self._session.post(
                url,
                headers=headers,
                files=files,
                data=data or {},
                timeout=TIMEOUT_SECONDS,
            )
        except requests.exceptions.ConnectionError as exc:
            raise TawseelException(-2, "Connection failed", "فشل الاتصال بالخادم") from exc
        except requests.exceptions.Timeout as exc:
            raise TawseelException(-3, "Request timed out", "انتهت مهلة الطلب") from exc
        elapsed = (time.perf_counter() - t0) * 1000
        logger.debug("← %s  %.0f ms", resp.status_code, elapsed)
        return self._parse(resp)

    # ── Internal ────────────────────────────────────────────────────────────────

    def _request(self, method: str, path: str, **kwargs) -> Any:
        url = f"{self._base_url}{path}"
        logger.debug("%s → %s", method, url)
        t0 = time.perf_counter()
        try:
            resp = self._session.request(
                method,
                url,
                headers=get_headers(),
                timeout=TIMEOUT_SECONDS,
                **kwargs,
            )
        except requests.exceptions.ConnectionError as exc:
            raise TawseelException(-2, "Connection failed", "فشل الاتصال بالخادم") from exc
        except requests.exceptions.Timeout as exc:
            raise TawseelException(-3, "Request timed out", "انتهت مهلة الطلب") from exc

        elapsed = (time.perf_counter() - t0) * 1000
        logger.debug("← %s  %.0f ms  %s", resp.status_code, elapsed, url)
        return self._parse(resp)

    @staticmethod
    def _parse(resp: requests.Response) -> Any:
        """
        Parse the TGA API response envelope.

        Every endpoint returns:
            { "data": <payload>, "errorCodes": [<int>, ...], "status": <bool> }

        status == true  AND errorCodes == [0]  → success, return data field
        status == false OR errorCodes != [0]   → raise TawseelException

        Some endpoints return data=true (boolean) on success — that is returned as-is.
        """
        if not resp.content:
            if resp.ok:
                return None
            raise TawseelException(
                resp.status_code,
                f"HTTP {resp.status_code} with empty body",
                f"خطأ HTTP {resp.status_code} بدون محتوى",
            )

        try:
            body = resp.json()
        except ValueError:
            raise TawseelException(
                -4,
                f"Non-JSON response (HTTP {resp.status_code}): {resp.text[:200]}",
                "رد غير صالح من الخادم",
            )

        # Standard 3scale envelope: { "data": ..., "errorCodes": [...], "status": bool }
        api_status = body.get("status")
        error_codes: list = body.get("errorCodes") or []

        if api_status is not None:
            # Filter out code 0 (success marker)
            real_errors = [c for c in error_codes if c != 0]
            if not api_status or real_errors:
                # Raise the first meaningful error code
                code = real_errors[0] if real_errors else -1
                raise TawseelException.from_error_code(code)
            logger.debug("API success status=true errorCodes=%s", error_codes)
            return body.get("data")

        # Fallback: no status field — check HTTP status
        if not resp.ok:
            raise TawseelException(
                resp.status_code,
                body.get("message", f"HTTP {resp.status_code}"),
                body.get("messageAr", "خطأ من الخادم"),
            )
        return body.get("data", body)
