"""
orders.py — Order Service (إدارة الطلبات)
Full order lifecycle: create → accept → assign driver → execute / cancel / reject.

Endpoints (all POST except Get):
    POST /external/api/order/create
    POST /external/api/order/accept
    POST /external/api/order/reject
    POST /external/api/order/assign-driver-to-order
    POST /external/api/order/edit-order-delivery-address
    POST /external/api/order/execute
    POST /external/api/order/cancel
    GET  /external/api/order/{refrenceCode}

Key field names (exact API spelling):
    - "referenceCode"        — order identifier in most endpoints
    - "orderId"              — used ONLY in cancel endpoint
    - "cancelationReasonId"  — single 'l' in cancelation (API spelling)
    - "storetName"           — API typo for store name (missing 'e'), preserved
    - "recipientMobileNumber"— full field name for recipient mobile
    - "refrenceCode"         — used as path param in Get Order (API typo)
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone
from enum import Enum
from typing import Any

from .base_client import TawseelClient
from .exceptions import TawseelException


# ─── Helpers ──────────────────────────────────────────────────────────────────

def _utcnow_iso() -> str:
    now = datetime.now(tz=timezone.utc)
    return now.strftime("%Y-%m-%dT%H:%M:%S.") + f"{now.microsecond // 1000:03d}Z"


# ─── Enumerations ─────────────────────────────────────────────────────────────

class OrderStatus(str, Enum):
    CREATED   = "CREATED"
    ACCEPTED  = "ACCEPTED"
    ASSIGNED  = "ASSIGNED"
    EXECUTED  = "EXECUTED"
    CANCELLED = "CANCELLED"
    REJECTED  = "REJECTED"

    def can_accept(self)        -> bool: return self is OrderStatus.CREATED
    def can_reject(self)        -> bool: return self is OrderStatus.CREATED
    def can_assign_driver(self) -> bool: return self is OrderStatus.ACCEPTED
    def can_execute(self)       -> bool: return self is OrderStatus.ASSIGNED
    def can_cancel(self)        -> bool: return self in {
        OrderStatus.CREATED, OrderStatus.ACCEPTED, OrderStatus.ASSIGNED
    }
    def is_terminal(self)       -> bool: return self in {
        OrderStatus.EXECUTED, OrderStatus.CANCELLED, OrderStatus.REJECTED
    }


# ─── Data models ──────────────────────────────────────────────────────────────

@dataclass
class CreateOrderRequest:
    """
    Payload for creating a new delivery order.

    Field notes
    -----------
    order_number           : Your internal reference, unique per day
    authority_id           : From lookups.authorities() — for government orders
    delivery_time          : ISO 8601 datetime string
    region_id              : From lookups.regions()
    city_id                : From lookups.cities(region_id)
    coordinates            : "lat,lng" string, e.g. "24.7136,46.6753"
    store_name             : Sender/store name (sent as "storetName" — API typo preserved)
    store_location         : "lat,lng" of pickup point
    category_id            : From lookups.order_categories()
    order_date             : ISO 8601 datetime string
    recipient_mobile       : Recipient mobile in 05XXXXXXXX format
    """
    order_number:      str
    authority_id:      str
    delivery_time:     str
    region_id:         str
    city_id:           str
    coordinates:       str
    store_name:        str
    store_location:    str
    category_id:       str
    order_date:        str
    recipient_mobile:  str

    def to_payload(self) -> dict[str, Any]:
        _validate_create(self)
        return {
            "orderNumber":           self.order_number,
            "authorityId":           self.authority_id,
            "deliveryTime":          self.delivery_time,
            "regionId":              self.region_id,
            "cityId":                self.city_id,
            "coordinates":           self.coordinates,
            "storetName":            self.store_name,      # API typo — intentional
            "storeLocation":         self.store_location,
            "categoryId":            self.category_id,
            "orderDate":             self.order_date,
            "recipientMobileNumber": self.recipient_mobile,
        }


@dataclass
class ExecuteOrderRequest:
    """
    Payload for executing (completing) a delivery order.

    price = price_without_delivery + delivery_price  (must balance exactly)
    """
    payment_method_id:      str    # From lookups.payment_methods()
    price:                  float  # Total order value
    price_without_delivery: float  # Item value only
    delivery_price:         float  # Delivery fee
    driver_income:          float  # Driver's share
    execution_time:         str = field(default_factory=_utcnow_iso)

    def to_payload(self, reference_code: str) -> dict[str, Any]:
        _validate_execute(self)
        return {
            "referenceCode":        reference_code,
            "executionTime":        self.execution_time,
            "paymentMethodId":      self.payment_method_id,
            "price":                self.price,
            "priceWithoutDelivery": self.price_without_delivery,
            "deliveryPrice":        self.delivery_price,
            "driverIncome":         self.driver_income,
        }


@dataclass(frozen=True)
class OrderInfo:
    """Parsed order record as returned by the API."""
    reference_code:    str
    order_number:      str
    status:            str
    driver_ref_code:   str   # driverReferenceCode
    region_id:         str
    city_id:           str
    coordinates:       str
    store_name:        str   # storetName from API
    category_id:       str
    execution_time:    str
    assignation_time:  str
    raw:               dict = field(default_factory=dict, compare=False)

    @classmethod
    def from_api(cls, data: dict[str, Any]) -> "OrderInfo":
        # data=true is returned for accept/reject/assign (boolean success)
        if not isinstance(data, dict):
            return cls(
                reference_code="", order_number="", status="", driver_ref_code="",
                region_id="", city_id="", coordinates="", store_name="",
                category_id="", execution_time="", assignation_time="", raw={},
            )
        return cls(
            reference_code=str(data.get("referenceCode") or ""),
            order_number=str(data.get("orderNumber") or ""),
            status=str(data.get("status") or ""),
            driver_ref_code=str(data.get("driverReferenceCode") or ""),
            region_id=str(data.get("regionId") or ""),
            city_id=str(data.get("cityId") or ""),
            coordinates=str(data.get("coordinates") or ""),
            store_name=str(data.get("storetName") or ""),   # API typo
            category_id=str(data.get("categoryId") or ""),
            execution_time=str(data.get("executionTime") or ""),
            assignation_time=str(data.get("assignationTime") or ""),
            raw=data,
        )


# ─── Validation ────────────────────────────────────────────────────────────────

def _validate_create(req: CreateOrderRequest) -> None:
    errors: list[str] = []
    for name, val in [
        ("order_number",  req.order_number),
        ("region_id",     req.region_id),
        ("city_id",       req.city_id),
        ("coordinates",   req.coordinates),
        ("store_name",    req.store_name),
        ("store_location",req.store_location),
        ("category_id",   req.category_id),
        ("order_date",    req.order_date),
        ("delivery_time", req.delivery_time),
    ]:
        if not val or not str(val).strip():
            errors.append(f"{name} is required")
    if not req.recipient_mobile:
        errors.append("recipient_mobile is required")
    if errors:
        raise ValueError("CreateOrderRequest validation failed:\n  • " + "\n  • ".join(errors))


def _validate_execute(req: ExecuteOrderRequest) -> None:
    errors: list[str] = []
    if not req.payment_method_id:
        errors.append("payment_method_id is required (use lookups.payment_methods())")
    for name, val in [
        ("price", req.price),
        ("price_without_delivery", req.price_without_delivery),
        ("delivery_price", req.delivery_price),
        ("driver_income", req.driver_income),
    ]:
        if val < 0:
            errors.append(f"{name} cannot be negative")
    expected = req.price_without_delivery + req.delivery_price
    if abs(req.price - expected) > 1e-6:
        errors.append(
            f"price ({req.price}) must equal price_without_delivery "
            f"({req.price_without_delivery}) + delivery_price ({req.delivery_price}) = {expected}"
        )
    if errors:
        raise ValueError("ExecuteOrderRequest validation failed:\n  • " + "\n  • ".join(errors))


# ─── Service ───────────────────────────────────────────────────────────────────

class OrderService:
    """
    Manage orders on the Tawseel platform.

    Happy path::

        svc = OrderService()

        order = svc.create(CreateOrderRequest(
            order_number="ORD-001",
            authority_id="1",
            delivery_time="2024-06-01T10:00:00.000Z",
            region_id="1",
            city_id="3",
            coordinates="24.7136,46.6753",
            store_name="متجر الرياض",
            store_location="24.7000,46.6500",
            category_id="1",
            order_date="2024-06-01T08:00:00.000Z",
            recipient_mobile="0512345678",
        ))

        ref = order.reference_code          # save this!

        svc.accept(ref)
        svc.assign_driver(ref, "1234567890")  # driver's id_number
        svc.execute(ref, ExecuteOrderRequest(
            payment_method_id="1",
            price=100.0,
            price_without_delivery=85.0,
            delivery_price=15.0,
            driver_income=10.0,
        ))
    """

    def __init__(self, client: TawseelClient | None = None) -> None:
        self._client = client or TawseelClient()

    def create(self, req: CreateOrderRequest) -> OrderInfo:
        """Create a new delivery order. Returns OrderInfo — save reference_code."""
        data = self._client.post("/external/api/order/create", payload=req.to_payload())
        return OrderInfo.from_api(data or {})

    def get(self, reference_code: str) -> OrderInfo:
        """
        Fetch full order details.
        Path param in API docs is spelled 'refrenceCode' (typo) — handled here.
        """
        if not reference_code:
            raise ValueError("reference_code is required")
        # API path uses the typo spelling in the URL parameter name
        data = self._client.get(f"/external/api/order/{reference_code}")
        return OrderInfo.from_api(data or {})

    def accept(self, reference_code: str, acceptance_datetime: str | None = None) -> bool:
        """
        Accept an order (status: CREATED → ACCEPTED).
        Raises OrderCannotBeAccepted (52) if not in CREATED state.
        Returns True on success.
        """
        if not reference_code:
            raise ValueError("reference_code is required")
        result = self._client.post("/external/api/order/accept", payload={
            "referenceCode":      reference_code,
            "acceptanceDateTime": acceptance_datetime or _utcnow_iso(),
        })
        return bool(result)

    def reject(self, reference_code: str) -> bool:
        """
        Reject an order (status: CREATED → REJECTED).
        Raises OrderCannotBeRejected (77).
        Returns True on success.
        """
        if not reference_code:
            raise ValueError("reference_code is required")
        result = self._client.post("/external/api/order/reject", payload={
            "referenceCode": reference_code,
        })
        return bool(result)

    def assign_driver(self, reference_code: str, driver_id_number: str) -> bool:
        """
        Assign a driver to an accepted order (status: ACCEPTED → ASSIGNED).
        driver_id_number is the driver's national ID / Iqama (idNumber field).
        Raises OrderNotAcceptedYet (54) if not yet accepted.
        Returns True on success.
        """
        if not reference_code:
            raise ValueError("reference_code is required")
        if not driver_id_number:
            raise ValueError("driver_id_number is required (driver's idNumber)")
        result = self._client.post("/external/api/order/assign-driver-to-order", payload={
            "referenceCode": reference_code,
            "idNumber":      driver_id_number,
        })
        return bool(result)

    def edit_delivery_address(
        self,
        reference_code: str,
        *,
        region_id: str,
        city_id: str,
        coordinates: str,
        store_location: str,
    ) -> bool:
        """
        Update the delivery address on an order.
        Returns True on success.
        """
        if not reference_code:
            raise ValueError("reference_code is required")
        result = self._client.post("/external/api/order/edit-order-delivery-address", payload={
            "referenceCode": reference_code,
            "regionId":      region_id,
            "cityId":        city_id,
            "coordinates":   coordinates,
            "storeLocation": store_location,
        })
        return bool(result)

    def execute(self, reference_code: str, req: ExecuteOrderRequest) -> OrderInfo:
        """
        Mark order as executed/delivered (status: ASSIGNED → EXECUTED).
        Raises DriverMustBeAssignedFirst (57) if no driver is assigned.
        """
        if not reference_code:
            raise ValueError("reference_code is required")
        data = self._client.post(
            "/external/api/order/execute",
            payload=req.to_payload(reference_code),
        )
        return OrderInfo.from_api(data or {})

    def cancel(self, reference_code: str, cancel_reason_id: str) -> bool:
        """
        Cancel an order.
        Raises OrderCannotBeCanceled (53) if not cancelable.

        cancel_reason_id : from lookups.cancel_reasons()

        Note: API uses "orderId" and "cancelationReasonId" (single 'l') in this endpoint.
        """
        if not reference_code:
            raise ValueError("reference_code is required")
        if not cancel_reason_id:
            raise ValueError("cancel_reason_id is required (use lookups.cancel_reasons())")
        result = self._client.post("/external/api/order/cancel", payload={
            "orderId":              reference_code,   # this endpoint uses orderId
            "cancelationReasonId":  cancel_reason_id, # single 'l' — API spelling
        })
        return bool(result)

    def full_lifecycle(
        self,
        create_req: CreateOrderRequest,
        driver_id_number: str,
        execute_req: ExecuteOrderRequest,
        *,
        cancel_reason_id: str | None = None,
    ) -> OrderInfo:
        """
        Convenience: run the full happy-path in one call.
        create → accept → assign_driver → execute

        If any step fails and cancel_reason_id is provided,
        a best-effort cancellation is attempted before re-raising.
        """
        order = self.create(create_req)
        ref = order.reference_code
        if not ref:
            raise TawseelException(-1, "create did not return referenceCode", "لم يُعاد referenceCode")

        try:
            self.accept(ref)
            self.assign_driver(ref, driver_id_number)
            return self.execute(ref, execute_req)
        except TawseelException:
            if cancel_reason_id:
                try:
                    self.cancel(ref, cancel_reason_id)
                except TawseelException:
                    pass  # cancellation is best-effort
            raise
