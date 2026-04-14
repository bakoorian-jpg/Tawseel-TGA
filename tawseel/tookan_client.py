"""
tookan_client.py — Tookan API Client
Minimal client for calling the Tookan API (driver app side).
Base URL: https://api.tookanapp.com/v2
Auth: api_key in every POST body
"""

from __future__ import annotations

import logging
from typing import Any

import requests

logger = logging.getLogger("tawseel.tookan")

TOOKAN_BASE_URL = "https://api.tookanapp.com/v2"
TIMEOUT = 30


class TookanClient:
    """
    Light wrapper around the Tookan REST API.

    Usage::

        client = TookanClient(api_key="YOUR_TOOKAN_API_KEY")
        task   = client.get_job_details(job_id=12345)
        fleet  = client.get_fleet_profile(fleet_id="67890")
    """

    def __init__(self, api_key: str) -> None:
        self._api_key = api_key
        self._session = requests.Session()

    # ── Tasks ──────────────────────────────────────────────────────────────────

    def get_job_details(self, job_id: int) -> dict[str, Any]:
        return self._post("/get_job_details", {"job_id": job_id})

    def get_job_by_order_id(self, order_id: str) -> dict[str, Any]:
        return self._post("/get_job_details_by_order_id", {"order_id": order_id})

    def assign_fleet_to_task(self, job_id: int, fleet_id: str) -> dict[str, Any]:
        return self._post("/assign_fleet_to_task", {"job_id": job_id, "fleet_id": fleet_id})

    def update_task_status(self, job_id: int, job_status: int) -> dict[str, Any]:
        return self._post("/update_task_status", {"job_id": job_id, "job_status": job_status})

    # ── Agents / Fleet ─────────────────────────────────────────────────────────

    def get_fleet_profile(self, fleet_id: str) -> dict[str, Any]:
        return self._post("/view_fleet_profile", {"fleet_id": fleet_id})

    def get_all_fleets(self, team_id: int | None = None) -> list[dict]:
        payload: dict[str, Any] = {}
        if team_id:
            payload["team_id"] = team_id
        result = self._post("/get_all_fleets", payload)
        return result if isinstance(result, list) else []

    # ── Internal ───────────────────────────────────────────────────────────────

    def _post(self, path: str, payload: dict) -> Any:
        url = f"{TOOKAN_BASE_URL}{path}"
        body = {"api_key": self._api_key, **payload}
        logger.debug("Tookan POST → %s", path)
        try:
            resp = self._session.post(url, json=body, timeout=TIMEOUT)
            resp.raise_for_status()
        except requests.exceptions.RequestException as exc:
            logger.error("Tookan request failed: %s", exc)
            raise

        data = resp.json()
        if data.get("status") not in (200, "200"):
            logger.warning("Tookan error: %s", data.get("message"))
        return data.get("data", data)
