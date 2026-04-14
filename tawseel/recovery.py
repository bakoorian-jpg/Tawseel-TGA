"""
recovery.py — Recovery Service (خدمة الاسترداد الجماعي)
Bulk xlsx upload/download for outage scenarios.

Uses a DIFFERENT base URL from the main API.
Auth is NOT header-based — companyName + password go in the request body/form fields.

Endpoints:
    POST /api/Order/uploadBulk    — multipart/form-data: companyName, password, xlsxFile
    POST /api/Order/downloadBulk  — JSON body: { "credential": { companyName, password, uuid } }

Response envelope: { "success": true/false, "errorCodes": [...], "data": {...} }
Note: uses "success" (not "status") unlike the main API.
"""

from __future__ import annotations

import io
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import requests

from .config import TIMEOUT_SECONDS, get_recovery_config
from .exceptions import StillProcessing, TawseelException

_DEFAULT_POLL_INTERVAL = 5    # seconds between polls
_DEFAULT_MAX_ATTEMPTS  = 60   # 60 × 5s = 5 minutes max


@dataclass(frozen=True)
class RecoveryUploadResult:
    """Result after a successful bulk upload — contains the UUID for polling."""
    uuid: str
    raw:  dict = field(default_factory=dict, compare=False)

    @classmethod
    def from_api(cls, data: dict[str, Any]) -> "RecoveryUploadResult":
        return cls(uuid=str(data.get("uuid") or ""), raw=data)


@dataclass
class RecoveryResult:
    """Final result after processing completes."""
    uuid:         str
    total_rows:   int
    success_rows: int
    failed_rows:  int
    errors:       list[dict]
    raw:          dict = field(default_factory=dict)

    @classmethod
    def from_api(cls, data: dict[str, Any]) -> "RecoveryResult":
        return cls(
            uuid=str(data.get("uuid") or ""),
            total_rows=int(data.get("totalRows") or 0),
            success_rows=int(data.get("successRows") or 0),
            failed_rows=int(data.get("failedRows") or 0),
            errors=data.get("errors") or [],
            raw=data,
        )


class RecoveryService:
    """
    Handles bulk order operations via the TGA Recovery API.

    Auth: companyName + password sent in request body / form fields (NOT headers).
    Base URL is separate from the main Tawseel API (see config.py RECOVERY block).

    Usage::

        svc = RecoveryService()

        # Download the official TGA template
        svc.download_template(Path("template.xlsx"))

        # Fill template with orders, then upload
        result = svc.upload_and_wait(Path("filled_template.xlsx"))
        print(f"{result.success_rows} ok / {result.failed_rows} failed")
        for err in result.errors:
            print(err)
    """

    def __init__(self) -> None:
        cfg = get_recovery_config()
        self._base_url    = cfg["base_url"].rstrip("/")
        self._company_name = cfg["company_name"]
        self._password     = cfg["password"]
        self._session      = requests.Session()

    # ── Core operations ─────────────────────────────────────────────────────────

    def upload_bulk(self, file_path: Path | str) -> RecoveryUploadResult:
        """
        Upload a bulk xlsx file.
        Returns RecoveryUploadResult with UUID to track processing.

        Raises InvalidBulkFileTemplate (99) for wrong format.
        Raises IllegalNumberOfRows (103) if rows outside 1–1000.
        """
        path = Path(file_path)
        if not path.exists():
            raise FileNotFoundError(f"File not found: {path}")
        if path.suffix.lower() != ".xlsx":
            raise ValueError(f"File must be .xlsx, got: {path.suffix}")
        return self._upload_bytes(path.read_bytes(), filename=path.name)

    def upload_bulk_bytes(self, content: bytes, filename: str = "bulk.xlsx") -> RecoveryUploadResult:
        """Upload raw bytes (e.g. from a web form upload)."""
        if not filename.endswith(".xlsx"):
            filename += ".xlsx"
        return self._upload_bytes(content, filename=filename)

    def get_result(self, uuid: str) -> RecoveryResult:
        """
        Check processing result for a previously uploaded file.
        Raises StillProcessing (104) if not finished yet — use wait_for_result() instead.
        """
        if not uuid:
            raise ValueError("uuid is required")

        url = f"{self._base_url}/api/Order/downloadBulk"
        payload = {
            "credential": {
                "companyName": self._company_name,
                "password":    self._password,
                "uuid":        uuid,
            }
        }
        try:
            resp = self._session.post(
                url,
                json=payload,
                headers={"Content-Type": "application/json"},
                timeout=TIMEOUT_SECONDS,
            )
        except requests.exceptions.ConnectionError as exc:
            raise TawseelException(-2, "Recovery connection failed", "فشل الاتصال بخادم الاسترداد") from exc
        except requests.exceptions.Timeout as exc:
            raise TawseelException(-3, "Recovery request timed out", "انتهت مهلة طلب الاسترداد") from exc

        data = self._parse(resp)
        return RecoveryResult.from_api(data or {})

    def wait_for_result(
        self,
        uuid: str,
        poll_interval: float = _DEFAULT_POLL_INTERVAL,
        max_attempts:  int   = _DEFAULT_MAX_ATTEMPTS,
    ) -> RecoveryResult:
        """
        Poll until processing completes, then return the result.

        poll_interval : seconds between attempts (default 5)
        max_attempts  : raises TimeoutError after this many attempts (default 60 = 5 min)
        """
        for attempt in range(1, max_attempts + 1):
            try:
                return self.get_result(uuid)
            except StillProcessing:
                if attempt == max_attempts:
                    raise TimeoutError(
                        f"Recovery file {uuid!r} still processing after "
                        f"{max_attempts * poll_interval:.0f} seconds"
                    )
                time.sleep(poll_interval)
        raise TimeoutError("Polling exhausted")  # unreachable, for type checkers

    def upload_and_wait(
        self,
        file_path: Path | str,
        poll_interval: float = _DEFAULT_POLL_INTERVAL,
        max_attempts:  int   = _DEFAULT_MAX_ATTEMPTS,
    ) -> RecoveryResult:
        """
        Convenience: upload a file and block until processing completes.
        Returns the final RecoveryResult.
        """
        upload = self.upload_bulk(file_path)
        return self.wait_for_result(upload.uuid, poll_interval, max_attempts)

    def download_template(self, save_to: Path | str) -> Path:
        """
        Download the official TGA xlsx template for bulk uploads.
        Template URL is the public production URL (same for test and prod).
        """
        # Template is a public file — no auth required
        template_url = "https://tawseelapi.ecloud.sa/public-files/delivery-apps-recoverytemplate"
        try:
            resp = self._session.get(template_url, timeout=TIMEOUT_SECONDS)
        except requests.exceptions.RequestException as exc:
            raise TawseelException(-2, "Template download failed", "فشل تنزيل القالب") from exc
        if not resp.ok:
            raise TawseelException(resp.status_code, f"HTTP {resp.status_code}", "خطأ في تنزيل القالب")
        dest = Path(save_to)
        dest.parent.mkdir(parents=True, exist_ok=True)
        dest.write_bytes(resp.content)
        return dest

    # ── Internal ─────────────────────────────────────────────────────────────────

    def _upload_bytes(self, content: bytes, filename: str) -> RecoveryUploadResult:
        url = f"{self._base_url}/api/Order/uploadBulk"
        files = {
            "xlsxFile": (
                filename,
                io.BytesIO(content),
                "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
            )
        }
        # Auth via form fields in the multipart body (NOT headers)
        form_data = {
            "companyName": self._company_name,
            "password":    self._password,
        }
        try:
            resp = self._session.post(
                url,
                files=files,
                data=form_data,
                timeout=TIMEOUT_SECONDS,
            )
        except requests.exceptions.ConnectionError as exc:
            raise TawseelException(-2, "Recovery connection failed", "فشل الاتصال بخادم الاسترداد") from exc
        except requests.exceptions.Timeout as exc:
            raise TawseelException(-3, "Recovery request timed out", "انتهت مهلة طلب الاسترداد") from exc

        data = self._parse(resp)
        return RecoveryUploadResult.from_api(data or {})

    @staticmethod
    def _parse(resp: requests.Response) -> Any:
        """
        Parse Recovery API response.
        Envelope: { "success": bool, "errorCodes": [...], "data": {...} }
        Note: uses "success" (not "status") unlike the main 3scale API.
        """
        if not resp.content:
            if resp.ok:
                return None
            raise TawseelException(resp.status_code, f"HTTP {resp.status_code}", "خطأ من خادم الاسترداد")

        try:
            body = resp.json()
        except ValueError:
            raise TawseelException(-4, f"Non-JSON recovery response: {resp.text[:200]}", "رد غير صالح")

        success     = body.get("success", False)
        error_codes = body.get("errorCodes") or []
        real_errors = [c for c in error_codes if c != 0]

        if not success or real_errors:
            code = real_errors[0] if real_errors else -1
            raise TawseelException.from_error_code(code)

        return body.get("data", body)
