"""
location_tracker.py — Real-time Driver Location Tracking
=========================================================

Polls Tookan for active driver locations every POLL_INTERVAL seconds
and forwards them to Tawseel.

WHY THIS IS NEEDED
------------------
TGA requires driver location to be reported every 10-20 seconds during
active deliveries. This is a critical requirement for platform approval.

HOW IT WORKS
------------
1. Maintains a set of "active jobs" (job_id → fleet_id mapping).
2. A background thread polls Tookan's /get_fleet_location every 15 seconds.
3. For each active driver, sends location to Tawseel.

NOTE ON TAWSEEL LOCATION ENDPOINT
----------------------------------
The Tawseel API documentation provided does not include a driver location
update endpoint. Confirm the correct endpoint with ELM/Tawseel support,
then fill in TAWSEEL_LOCATION_ENDPOINT below.

USAGE
-----
    tracker = LocationTracker(tookan_api_key="...", tawseel_client=client)
    tracker.start()

    # When a driver is assigned to an order:
    tracker.add_job(job_id=12345, fleet_id="67890", reference_code="REF-ABC")

    # When order completes/cancels:
    tracker.remove_job(job_id=12345)

    # On shutdown:
    tracker.stop()
"""

from __future__ import annotations

import logging
import threading
import time
from dataclasses import dataclass
from typing import Any

from .base_client import TawseelClient
from .tookan_client import TookanClient

logger = logging.getLogger("tawseel.location")

# ── Config ─────────────────────────────────────────────────────────────────────
POLL_INTERVAL = 15  # seconds — within TGA's 10-20s requirement

# TODO: Confirm this endpoint with ELM/Tawseel support team.
# It is not documented in the provided PDFs.
# Likely candidates:
#   POST /external/api/driver/location
#   POST /external/api/order/driver-location
TAWSEEL_LOCATION_ENDPOINT = "/external/api/driver/location"


@dataclass
class _ActiveJob:
    job_id:         int
    fleet_id:       str
    reference_code: str   # Tawseel referenceCode


class LocationTracker:
    """
    Background service: polls Tookan driver locations and pushes to Tawseel.

    Thread-safe. Safe to call add_job/remove_job from any thread.
    """

    def __init__(
        self,
        tookan_api_key: str,
        tawseel_client: TawseelClient | None = None,
        poll_interval: int = POLL_INTERVAL,
    ) -> None:
        self._tookan       = TookanClient(tookan_api_key)
        self._tawseel      = tawseel_client or TawseelClient()
        self._interval     = poll_interval
        self._jobs: dict[int, _ActiveJob] = {}   # job_id → _ActiveJob
        self._lock         = threading.Lock()
        self._stop_event   = threading.Event()
        self._thread: threading.Thread | None = None

    # ── Public API ──────────────────────────────────────────────────────────────

    def start(self) -> None:
        """Start the background polling thread."""
        if self._thread and self._thread.is_alive():
            return
        self._stop_event.clear()
        self._thread = threading.Thread(
            target=self._run,
            name="LocationTracker",
            daemon=True,   # dies when main process exits
        )
        self._thread.start()
        logger.info("LocationTracker started — polling every %ds", self._interval)

    def stop(self) -> None:
        """Stop the background thread gracefully."""
        self._stop_event.set()
        if self._thread:
            self._thread.join(timeout=self._interval + 2)
        logger.info("LocationTracker stopped")

    def add_job(self, job_id: int, fleet_id: str, reference_code: str) -> None:
        """Register a job for location tracking (call when driver is assigned)."""
        with self._lock:
            self._jobs[job_id] = _ActiveJob(
                job_id=job_id,
                fleet_id=fleet_id,
                reference_code=reference_code,
            )
        logger.info("Tracking started: job_id=%d fleet_id=%s ref=%s",
                    job_id, fleet_id, reference_code)

    def remove_job(self, job_id: int) -> None:
        """Unregister a job (call when order completes or cancels)."""
        with self._lock:
            job = self._jobs.pop(job_id, None)
        if job:
            logger.info("Tracking stopped: job_id=%d ref=%s", job_id, job.reference_code)

    def active_count(self) -> int:
        """Number of jobs currently being tracked."""
        with self._lock:
            return len(self._jobs)

    # ── Background loop ─────────────────────────────────────────────────────────

    def _run(self) -> None:
        """Main polling loop — runs in background thread."""
        while not self._stop_event.wait(timeout=self._interval):
            with self._lock:
                jobs = list(self._jobs.values())

            if not jobs:
                continue

            logger.debug("Location poll: %d active jobs", len(jobs))
            for job in jobs:
                try:
                    self._poll_and_push(job)
                except Exception as exc:
                    logger.warning(
                        "Location update failed: job_id=%d fleet_id=%s — %s",
                        job.job_id, job.fleet_id, exc,
                    )

    def _poll_and_push(self, job: _ActiveJob) -> None:
        """Fetch location from Tookan and push to Tawseel for one job."""
        # Step 1: Get location from Tookan
        location = self._tookan.get_fleet_location(job.fleet_id)
        if not location:
            logger.debug("No location data for fleet_id=%s", job.fleet_id)
            return

        lat = location.get("latitude") or location.get("lat")
        lng = location.get("longitude") or location.get("lng") or location.get("long")

        if not lat or not lng:
            logger.debug("Empty lat/lng for fleet_id=%s: %s", job.fleet_id, location)
            return

        # Step 2: Push to Tawseel
        # ⚠️  CONFIRM endpoint with ELM. This endpoint is not in the provided docs.
        self._push_to_tawseel(
            reference_code=job.reference_code,
            lat=float(lat),
            lng=float(lng),
        )

        logger.debug("Location pushed: ref=%s lat=%s lng=%s", job.reference_code, lat, lng)

    def _push_to_tawseel(self, reference_code: str, lat: float, lng: float) -> None:
        """
        Send driver coordinates to Tawseel.

        ⚠️  IMPORTANT: TAWSEEL_LOCATION_ENDPOINT is not confirmed.
        Contact ELM support to get the correct endpoint before going live.
        Possible body structure (to be confirmed):
            { "referenceCode": "...", "latitude": 24.7, "longitude": 46.6 }
        """
        payload: dict[str, Any] = {
            "referenceCode": reference_code,
            "latitude":      lat,
            "longitude":     lng,
        }
        try:
            self._tawseel.post(TAWSEEL_LOCATION_ENDPOINT, payload=payload)
        except Exception as exc:
            # Don't crash — location updates are best-effort
            # A missed update is recoverable; a crash is not.
            logger.warning("Tawseel location POST failed ref=%s: %s", reference_code, exc)
