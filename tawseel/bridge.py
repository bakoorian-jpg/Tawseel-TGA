"""
bridge.py — Tookan ↔ Tawseel Integration Bridge
=================================================

Receives Tookan webhook events and maps them to Tawseel API calls.

FLOW
----
Tookan: Task Created   (job_status=6) → Tawseel: create_order
Tookan: Task Accepted  (job_status=7) → Tawseel: accept_order
Tookan: Fleet Assigned (job_status=0) → Tawseel: assign_driver
Tookan: Task Complete  (job_status=2) → Tawseel: execute_order
Tookan: Task Canceled  (job_status=9) → Tawseel: cancel_order
Tookan: Task Failed    (job_status=3) → Tawseel: cancel_order

PRICE FIELDS
------------
Tookan stores order price in custom fields. Set up a custom field template
in Tookan named "TawseelPricing" with these labels:
    - price                  (total order value, SAR)
    - price_without_delivery (item value only)
    - delivery_price         (delivery fee)
    - driver_income          (driver's share)

If those fields are absent, the bridge falls back to BridgeConfig defaults.

DRIVER ID
---------
Each driver's Saudi National ID / Iqama must be stored in Tookan's
"License" field on their agent profile. The bridge reads it from there.

WEBHOOK SECURITY
----------------
Set tookan_shared_secret in BridgeConfig (same value as in Tookan dashboard
Settings → Notifications → Shared Secret). The bridge rejects any webhook
where the secret doesn't match.
"""

from __future__ import annotations

import hmac
import logging
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any

from .orders import CreateOrderRequest, ExecuteOrderRequest, OrderService
from .tookan_client import TookanClient

# LocationTracker is imported lazily to avoid circular imports

logger = logging.getLogger("tawseel.bridge")


# ── Tookan job_status codes ────────────────────────────────────────────────────
class TookanStatus:
    ASSIGNED    = 0   # fleet assigned
    STARTED     = 1   # driver en route
    SUCCESSFUL  = 2   # delivered ✓
    FAILED      = 3   # failed delivery
    IN_PROGRESS = 4   # driver arrived at location
    UNASSIGNED  = 6   # newly created, no driver yet
    ACCEPTED    = 7   # accepted / acknowledged
    DECLINED    = 8
    CANCELLED   = 9
    DELETED     = 10


# ── Result object ──────────────────────────────────────────────────────────────

@dataclass
class BridgeResult:
    tookan_job_id: int
    tookan_status: int
    action_taken:  str
    tawseel_ref:   str  = ""
    success:       bool = True
    error:         str  = ""

    def __str__(self) -> str:
        ok = "OK" if self.success else f"ERROR: {self.error}"
        return f"[job={self.tookan_job_id} status={self.tookan_status}] {self.action_taken} → {ok}"


# ── Bridge config ──────────────────────────────────────────────────────────────

@dataclass
class BridgeConfig:
    """
    Static Tawseel IDs — get them by running: python -m tawseel.main

    region_id          : from lookups.regions()
    city_id            : from lookups.cities(region_id)
    category_id        : from lookups.order_categories()
    authority_id       : from lookups.authorities()
    payment_method_id  : from lookups.payment_methods()
    cancel_reason_id   : from lookups.cancel_reasons()
    tookan_shared_secret: from Tookan dashboard → Settings → Notifications → Shared Secret
                          Leave empty to skip verification (not recommended for production)
    default_price      : fallback price (SAR) if Tookan custom fields are missing
    driver_income_ratio: driver's share of delivery_price (0.0–1.0)
    """
    region_id:            str
    city_id:              str
    category_id:          str
    authority_id:         str
    payment_method_id:    str
    cancel_reason_id:     str
    tookan_shared_secret: str   = ""
    default_price:        float = 50.0
    driver_income_ratio:  float = 0.7


# ── Reference store ────────────────────────────────────────────────────────────
# Maps Tookan job_id → { "ref": Tawseel referenceCode, "price_data": {...} }
# Replace with a DB-backed store in production (Redis, SQLite, Postgres, etc.)

class _RefStore:
    def __init__(self) -> None:
        self._data: dict[int, dict] = {}

    def save(self, job_id: int, reference_code: str, price_data: dict | None = None) -> None:
        self._data[job_id] = {"ref": reference_code, "price": price_data or {}}
        logger.debug("RefStore save: job_id=%d ref=%s", job_id, reference_code)

    def get_ref(self, job_id: int) -> str | None:
        return (self._data.get(job_id) or {}).get("ref")

    def get_price(self, job_id: int) -> dict:
        return (self._data.get(job_id) or {}).get("price") or {}

    def delete(self, job_id: int) -> None:
        self._data.pop(job_id, None)


_ref_store = _RefStore()


# ── Main bridge class ──────────────────────────────────────────────────────────

class TookanTawseelBridge:
    """
    Handles Tookan webhook events → Tawseel API calls.

    Usage (Flask)::

        bridge = TookanTawseelBridge(
            tookan_api_key="YOUR_KEY",
            config=BridgeConfig(
                region_id="1", city_id="3", category_id="1",
                authority_id="1", payment_method_id="1", cancel_reason_id="1",
                tookan_shared_secret="YOUR_SECRET",
            ),
        )

        @app.route("/webhook/tookan", methods=["POST"])
        def webhook():
            result = bridge.handle_webhook(request.get_json(force=True))
            return {"ok": result.success}, 200
    """

    def __init__(
        self,
        tookan_api_key: str,
        config: BridgeConfig,
        ref_store: _RefStore | None = None,
        enable_location_tracking: bool = True,
    ) -> None:
        self._tookan = TookanClient(tookan_api_key)
        self._orders = OrderService()
        self._config = config
        self._store  = ref_store or _ref_store

        # Location tracker — fulfills TGA's 10-20s real-time tracking requirement
        self._tracker = None
        if enable_location_tracking:
            from .location_tracker import LocationTracker
            self._tracker = LocationTracker(tookan_api_key=tookan_api_key)
            self._tracker.start()

    # ── Public ─────────────────────────────────────────────────────────────────

    def handle_webhook(self, payload: dict[str, Any]) -> BridgeResult:
        """
        Main entry point. Pass the raw Tookan webhook JSON body.
        Returns BridgeResult describing what was done.
        """
        # 1. Security: verify shared secret
        if self._config.tookan_shared_secret:
            secret_in_payload = str(payload.get("tookan_shared_secret") or "")
            if not hmac.compare_digest(secret_in_payload, self._config.tookan_shared_secret):
                logger.warning("Webhook rejected — shared secret mismatch")
                return BridgeResult(0, -1, "rejected — invalid shared secret", success=False,
                                    error="shared secret mismatch")

        job_id     = int(payload.get("job_id") or 0)
        job_status = int(payload.get("job_status") if payload.get("job_status") is not None else -1)

        if not job_id:
            return BridgeResult(0, job_status, "ignored — no job_id")

        logger.info("Webhook: job_id=%d job_status=%d order_id=%s",
                    job_id, job_status, payload.get("order_id"))

        handlers = {
            TookanStatus.UNASSIGNED:  self._on_task_created,
            TookanStatus.ACCEPTED:    self._on_task_accepted,
            TookanStatus.ASSIGNED:    self._on_driver_assigned,
            TookanStatus.STARTED:     self._on_task_picked_up,    # driver picked up order
            TookanStatus.IN_PROGRESS: self._on_task_picked_up,    # driver arrived at customer
            TookanStatus.SUCCESSFUL:  self._on_task_completed,
            TookanStatus.FAILED:      self._on_task_failed_or_cancelled,
            TookanStatus.CANCELLED:   self._on_task_failed_or_cancelled,
        }

        handler = handlers.get(job_status)
        if not handler:
            return BridgeResult(job_id, job_status,
                                f"ignored — status {job_status} needs no Tawseel action")

        try:
            return handler(job_id, payload)
        except Exception as exc:
            logger.exception("Bridge error job_id=%d status=%d", job_id, job_status)
            return BridgeResult(job_id, job_status, "exception", success=False, error=str(exc))

    def sync_driver(self, fleet_id: str) -> bool:
        """
        Manually sync a single Tookan driver to Tawseel.
        Call this once per driver when onboarding (Tookan has no webhook for new agents).

        Returns True on success, False if driver data is incomplete.

        Usage::
            bridge.sync_driver("TOOKAN_FLEET_ID")
        """
        from .drivers import DriverRequest, DriverService

        try:
            profile = self._tookan.get_fleet_profile(fleet_id)
        except Exception as exc:
            logger.error("Failed to fetch Tookan fleet profile fleet_id=%s: %s", fleet_id, exc)
            return False

        id_number = str(profile.get("license") or "")
        if not id_number or not id_number.isdigit() or len(id_number) not in (9, 10):
            logger.error(
                "Driver fleet_id=%s has no valid Saudi ID in 'license' field. "
                "Ask the driver to update their license field in Tookan.", fleet_id
            )
            return False

        # Validate mobile before proceeding
        mobile = _normalize_mobile(str(profile.get("phone") or ""))
        if not mobile or len(mobile) != 10 or not mobile.startswith("05"):
            logger.error(
                "Driver fleet_id=%s has invalid mobile '%s'. "
                "Correct it in Tookan → Agent Profile → Phone.", fleet_id, mobile
            )
            return False

        cfg = self._config
        req = DriverRequest(
            id_number=id_number,
            identity_type_id="1",   # 1=Saudi national ID, 2=Iqama — adjust per driver
            nationality_id="113",   # 113=Saudi — get exact value from lookups.nationalities()
            region_id=cfg.region_id,
            city_id=cfg.city_id,
            car_type_id="1",        # get from lookups.car_types()
            mobile=mobile,
            # car_number must be stored in Tookan's transport_desc as "1234ABC" format
            # (4 digits + 3 uppercase letters). Driver must enter it correctly in Tookan.
            car_number=str(profile.get("transport_desc") or "").upper().replace(" ", ""),
            # IMPORTANT: The following fields CANNOT be auto-filled from Tookan.
            # They must be collected from the driver directly and stored somewhere accessible.
            # date_of_birth: 8-digit integer YYYYMMDD (Gregorian for residents, Hijri for Saudis)
            # registration_date: ISO 8601 datetime of Iqama/ID registration
            # vehicle_sequence_number: from vehicle registration card
            # This method is a STARTING POINT — the developer must extend it with real data.
            date_of_birth=0,                              # MUST BE REPLACED with real value
            registration_date="",                         # MUST BE REPLACED with real value
            vehicle_sequence_number="",                   # MUST BE REPLACED with real value
        )

        # Refuse to submit if critical fields are missing
        if not req.car_number or not req.date_of_birth or not req.registration_date:
            logger.error(
                "Driver fleet_id=%s is missing required fields (car_number, date_of_birth, "
                "registration_date, vehicle_sequence_number). "
                "These must be collected from the driver and stored before syncing.", fleet_id
            )
            return False

        from .exceptions import DriverAlreadyExist
        try:
            DriverService().create(req)
            logger.info("Driver synced: fleet_id=%s id_number=%s", fleet_id, id_number)
            return True
        except DriverAlreadyExist:
            logger.info("Driver already in Tawseel: id_number=%s", id_number)
            return True
        except Exception as exc:
            logger.error("Failed to create driver in Tawseel: %s", exc)
            return False

    # ── Event handlers ─────────────────────────────────────────────────────────

    def _on_task_created(self, job_id: int, payload: dict) -> BridgeResult:
        """Task created → Tawseel create_order. Stores price data for execute step."""
        # Idempotency: if we already created a Tawseel order for this job, skip.
        # Tookan retries webhooks on server errors — this prevents duplicate orders.
        if self._store.get_ref(job_id):
            logger.info("Duplicate webhook ignored: job_id=%d already has a referenceCode", job_id)
            return BridgeResult(job_id, TookanStatus.UNASSIGNED, "skipped — duplicate webhook",
                                tawseel_ref=self._store.get_ref(job_id))

        cfg = self._config
        now = _utcnow()

        # Extract price from Tookan custom fields (set up "TawseelPricing" template)
        price_data = _extract_pricing(payload, cfg)

        req = CreateOrderRequest(
            order_number=str(payload.get("order_id") or job_id),
            authority_id=cfg.authority_id,
            delivery_time=_to_iso(payload.get("job_delivery_datetime")) or now,
            region_id=cfg.region_id,
            city_id=cfg.city_id,
            coordinates=_coords(payload.get("latitude"), payload.get("longitude")),
            store_name=str(payload.get("job_pickup_name") or "Store"),
            store_location=_coords(
                payload.get("job_pickup_latitude"),
                payload.get("job_pickup_longitude"),
            ),
            category_id=cfg.category_id,
            order_date=_to_iso(payload.get("job_pickup_datetime")) or now,
            recipient_mobile=_normalize_mobile(str(payload.get("customer_phone") or ""))
                             or "0500000000",  # fallback if phone missing/invalid in Tookan
        )

        order = self._orders.create(req)
        self._store.save(job_id, order.reference_code, price_data)
        logger.info("Order created: job_id=%d → ref=%s", job_id, order.reference_code)
        return BridgeResult(job_id, TookanStatus.UNASSIGNED, "create_order",
                            tawseel_ref=order.reference_code)

    def _on_task_accepted(self, job_id: int, _payload: dict) -> BridgeResult:
        """Task accepted → Tawseel accept_order."""
        ref = self._store.get_ref(job_id)
        if not ref:
            return BridgeResult(job_id, TookanStatus.ACCEPTED, "skipped — no referenceCode")
        self._orders.accept(ref)
        logger.info("Order accepted: job_id=%d ref=%s", job_id, ref)
        return BridgeResult(job_id, TookanStatus.ACCEPTED, "accept_order", tawseel_ref=ref)

    def _on_driver_assigned(self, job_id: int, payload: dict) -> BridgeResult:
        """Fleet assigned → Tawseel assign_driver."""
        ref = self._store.get_ref(job_id)
        if not ref:
            return BridgeResult(job_id, TookanStatus.ASSIGNED, "skipped — no referenceCode")

        fleet_id         = str(payload.get("fleet_id") or "")
        driver_id_number = self._resolve_driver_id(fleet_id, payload)

        if not driver_id_number:
            msg = (f"Driver fleet_id={fleet_id} has no Saudi ID in 'license' field. "
                   "Update it in Tookan → Agent Profile → License.")
            logger.error(msg)
            return BridgeResult(job_id, TookanStatus.ASSIGNED,
                                "assign_driver skipped — missing idNumber",
                                tawseel_ref=ref, success=False, error=msg)

        # Accept first (in case it wasn't already — handles race condition)
        try:
            self._orders.accept(ref)
        except Exception:
            pass  # already accepted — fine

        self._orders.assign_driver(ref, driver_id_number)
        logger.info("Driver assigned: job_id=%d fleet=%s id=%s ref=%s",
                    job_id, fleet_id, driver_id_number, ref)

        # Start real-time location tracking for this job
        if self._tracker:
            self._tracker.add_job(job_id=job_id, fleet_id=fleet_id, reference_code=ref)

        return BridgeResult(job_id, TookanStatus.ASSIGNED, "assign_driver", tawseel_ref=ref)

    def _on_task_completed(self, job_id: int, _payload: dict) -> BridgeResult:
        """Task successful → Tawseel execute_order with correct pricing."""
        ref = self._store.get_ref(job_id)
        if not ref:
            return BridgeResult(job_id, TookanStatus.SUCCESSFUL, "skipped — no referenceCode")

        # Use stored price data (captured at create time from custom fields)
        price_data = self._store.get_price(job_id)

        execute_req = ExecuteOrderRequest(
            payment_method_id=self._config.payment_method_id,
            price=price_data.get("price", self._config.default_price),
            price_without_delivery=price_data.get("price_without_delivery",
                                                   round(self._config.default_price * 0.8, 2)),
            delivery_price=price_data.get("delivery_price",
                                          round(self._config.default_price * 0.2, 2)),
            driver_income=price_data.get("driver_income",
                                         round(self._config.default_price * 0.2
                                               * self._config.driver_income_ratio, 2)),
        )

        self._orders.execute(ref, execute_req)
        self._store.delete(job_id)
        if self._tracker:
            self._tracker.remove_job(job_id)   # stop location tracking
        logger.info("Order executed: job_id=%d ref=%s price=%.2f",
                    job_id, ref, execute_req.price)
        return BridgeResult(job_id, TookanStatus.SUCCESSFUL, "execute_order", tawseel_ref=ref)

    def _on_task_picked_up(self, job_id: int, _payload: dict) -> BridgeResult:
        """
        Tookan: driver started (status=1) or arrived (status=4) → PICKED_UP.
        Tawseel has no dedicated picked-up endpoint — we log the event.
        Location tracking (the real-time requirement) is handled by LocationTracker.
        """
        ref = self._store.get_ref(job_id)
        if not ref:
            return BridgeResult(job_id, TookanStatus.STARTED, "skipped — no referenceCode")
        logger.info("Order picked up: job_id=%d ref=%s (location tracker handles real-time)", job_id, ref)
        return BridgeResult(job_id, TookanStatus.STARTED, "picked_up — logged", tawseel_ref=ref)

    def _on_task_failed_or_cancelled(self, job_id: int, payload: dict) -> BridgeResult:
        """Task failed/cancelled → Tawseel cancel_order."""
        ref = self._store.get_ref(job_id)
        if not ref:
            return BridgeResult(job_id, int(payload.get("job_status", 9)),
                                "skipped — no referenceCode")
        try:
            self._orders.cancel(ref, self._config.cancel_reason_id)
        except Exception as exc:
            logger.warning("Cancel may have already been applied: %s", exc)

        self._store.delete(job_id)
        if self._tracker:
            self._tracker.remove_job(job_id)   # stop location tracking
        logger.info("Order cancelled: job_id=%d ref=%s", job_id, ref)
        return BridgeResult(job_id, int(payload.get("job_status", 9)),
                            "cancel_order", tawseel_ref=ref)

    # ── Helpers ────────────────────────────────────────────────────────────────

    def _resolve_driver_id(self, fleet_id: str, payload: dict) -> str:
        """Find driver's Saudi ID. Checks webhook custom_fields first, then Tookan profile."""
        # 1. Check custom_fields in webhook payload
        for cf in payload.get("custom_fields") or []:
            label = str(cf.get("label") or "").lower()
            if "id" in label or "هوية" in label or "iqama" in label:
                val = str(cf.get("data") or cf.get("value") or "")
                if val.isdigit() and len(val) in (9, 10):
                    return val

        # 2. Fetch from Tookan agent profile → license field
        if not fleet_id:
            return ""
        try:
            profile  = self._tookan.get_fleet_profile(fleet_id)
            license_ = str(profile.get("license") or "")
            if license_.isdigit() and len(license_) in (9, 10):
                return license_
        except Exception as exc:
            logger.warning("Could not fetch fleet profile fleet_id=%s: %s", fleet_id, exc)

        return ""


# ── Helpers ────────────────────────────────────────────────────────────────────

def _utcnow() -> str:
    now = datetime.now(tz=timezone.utc)
    return now.strftime("%Y-%m-%dT%H:%M:%S.") + f"{now.microsecond // 1000:03d}Z"


def _to_iso(dt_str: str | None) -> str | None:
    """Convert Tookan datetime 'YYYY-MM-DD HH:MM:SS' to ISO 8601 for Tawseel."""
    if not dt_str:
        return None
    try:
        dt = datetime.strptime(str(dt_str), "%Y-%m-%d %H:%M:%S")
        return dt.strftime("%Y-%m-%dT%H:%M:%S.000Z")
    except ValueError:
        return str(dt_str)  # already in some other format, pass through


def _coords(lat: Any, lng: Any) -> str:
    """Format lat/lng as 'lat,lng' string. Falls back to Riyadh center."""
    try:
        return f"{float(lat)},{float(lng)}"
    except (TypeError, ValueError):
        return "24.7136,46.6753"


def _normalize_mobile(mobile: str) -> str:
    """
    Normalize any Saudi mobile format → 05XXXXXXXX (10 digits).
    Returns empty string if the result is not a valid Saudi mobile.
    """
    mobile = mobile.strip().replace(" ", "").replace("-", "")
    if mobile.startswith("+966"):
        mobile = "0" + mobile[4:]
    elif mobile.startswith("966"):
        mobile = "0" + mobile[3:]
    # Validate result: must be 10 digits starting with 05
    if len(mobile) == 10 and mobile.startswith("05") and mobile.isdigit():
        return mobile
    return ""  # invalid — caller must handle


def _extract_pricing(payload: dict, cfg: BridgeConfig) -> dict:
    """
    Read price fields from Tookan custom_fields (template: TawseelPricing).
    Falls back to BridgeConfig defaults if fields are missing.

    Set up a custom field template in Tookan named "TawseelPricing" with:
        label: price                  → total order value (SAR)
        label: price_without_delivery → item price only
        label: delivery_price         → delivery fee
        label: driver_income          → driver's share
    """
    cf_map: dict[str, float] = {}
    for cf in payload.get("custom_fields") or []:
        label = str(cf.get("label") or "").lower().strip().replace(" ", "_")
        try:
            cf_map[label] = float(cf.get("data") or cf.get("value") or 0)
        except (ValueError, TypeError):
            pass

    default_price    = cf_map.get("price", cfg.default_price)
    default_delivery = cf_map.get("delivery_price", round(default_price * 0.2, 2))
    default_items    = cf_map.get("price_without_delivery", round(default_price - default_delivery, 2))
    default_income   = cf_map.get("driver_income", round(default_delivery * cfg.driver_income_ratio, 2))

    return {
        "price":                  default_price,
        "price_without_delivery": default_items,
        "delivery_price":         default_delivery,
        "driver_income":          default_income,
    }
