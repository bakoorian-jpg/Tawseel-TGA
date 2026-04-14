"""
drivers.py — Driver Service (إدارة المندوبين)
Full CRUD + deactivation for Tawseel delivery drivers.

Endpoints (all POST except Get):
    POST /external/api/driver/create
    POST /external/api/driver/edit
    POST /external/api/driver/deactivate/{idNumber}
    GET  /external/api/driver/{idNumber}

Response envelope: { "data": {...}, "errorCodes": [0], "status": true }
Driver identifier in responses: "refrenceCode" (API typo — missing 'e', intentional)
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Any

from .base_client import TawseelClient

# ─── Compiled regex patterns ────────────────────────────────────────────────────
# id must start with 1 (Saudi citizen) or 2 (resident/Iqama), exactly 10 digits
_RE_ID_NUMBER  = re.compile(r"^[12]\d{9}$")
_RE_MOBILE     = re.compile(r"^05\d{8}$")
# Saudi plate: 4 digits + 3 uppercase ASCII letters, e.g. "1234ERS"
_RE_CAR_NUMBER = re.compile(r"^[0-9]{4}[A-Z]{3}$")
_RE_DOB        = re.compile(r"^\d{8}$")   # YYYYMMDD integer as string


# ─── Data models ──────────────────────────────────────────────────────────────

@dataclass
class DriverRequest:
    """
    Payload for creating or editing a driver.

    Field notes
    -----------
    id_number              : 10-digit string starting with 1 (Saudi) or 2 (resident)
    identity_type_id       : From lookups.identity_types()
    nationality_id         : From lookups.nationalities()  (countries-list)
    region_id              : From lookups.regions()
    city_id                : From lookups.cities(region_id)
    car_type_id            : From lookups.car_types()
    mobile                 : Saudi mobile 05XXXXXXXX (10 digits)
    car_number             : 4 digits + 3 uppercase letters, e.g. "1234ERS"
    date_of_birth          : Integer YYYYMMDD (Gregorian for residents, Hijri for Saudis)
    registration_date      : ISO 8601 string e.g. "2020-04-03T08:07:40.213Z"
    vehicle_sequence_number: From vehicle registration card
    refrence_code          : Driver's reference code from a prior create (required for edit only)
                             Note: "refrence" is the API's own typo — kept intentionally.
    """
    id_number:               str
    identity_type_id:        str
    nationality_id:          str
    region_id:               str
    city_id:                 str
    car_type_id:             str
    mobile:                  str
    car_number:              str
    date_of_birth:           int   # YYYYMMDD integer
    registration_date:       str   # ISO 8601
    vehicle_sequence_number: str
    refrence_code:           str = ""   # required for edit, empty for create

    def to_create_payload(self) -> dict[str, Any]:
        _validate(self)
        return {
            "identityTypeId":        self.identity_type_id,
            "idNumber":              self.id_number,
            "dateOfBirth":           self.date_of_birth,
            "registrationDate":      self.registration_date,
            "mobile":                self.mobile,
            "regionId":              self.region_id,
            "cityId":                self.city_id,
            "carTypeId":             self.car_type_id,
            "carNumber":             self.car_number,
            "vehicleSequenceNumber": self.vehicle_sequence_number,
        }

    def to_edit_payload(self) -> dict[str, Any]:
        if not self.refrence_code:
            raise ValueError("refrence_code is required for edit — use the value returned by create()")
        _validate(self)
        payload = self.to_create_payload()
        payload["refrenceCode"] = self.refrence_code   # API's own typo preserved
        return payload


@dataclass(frozen=True)
class DriverInfo:
    """Parsed driver record as returned by the API."""
    refrence_code:           str   # API typo intentional
    id_number:               str
    mobile:                  str
    region_id:               str
    city_id:                 str
    car_type_id:             str
    car_number:              str
    identity_type_id:        str
    date_of_birth:           int
    registration_date:       str
    vehicle_sequence_number: str
    raw:                     dict = field(default_factory=dict, compare=False)

    @classmethod
    def from_api(cls, data: dict[str, Any]) -> "DriverInfo":
        return cls(
            refrence_code=str(data.get("refrenceCode") or ""),  # API typo
            id_number=str(data.get("idNumber") or ""),
            mobile=str(data.get("mobile") or ""),
            region_id=str(data.get("regionId") or ""),
            city_id=str(data.get("cityId") or ""),
            car_type_id=str(data.get("carTypeId") or ""),
            car_number=str(data.get("carNumber") or ""),
            identity_type_id=str(data.get("identityTypeId") or ""),
            date_of_birth=int(data.get("dateOfBirth") or 0),
            registration_date=str(data.get("registrationDate") or ""),
            vehicle_sequence_number=str(data.get("vehicleSequenceNumber") or ""),
            raw=data,
        )


# ─── Validation ────────────────────────────────────────────────────────────────

def _validate(req: DriverRequest) -> None:
    errors: list[str] = []

    if not isinstance(req.id_number, str) or not _RE_ID_NUMBER.match(req.id_number):
        errors.append(
            "id_number must be 10 digits starting with 1 (Saudi) or 2 (resident), "
            f"got: {req.id_number!r}"
        )
    if not isinstance(req.mobile, str) or not _RE_MOBILE.match(req.mobile):
        errors.append(f"mobile must be 05XXXXXXXX (10 digits), got: {req.mobile!r}")

    if not isinstance(req.car_number, str) or not _RE_CAR_NUMBER.match(req.car_number):
        errors.append(
            f"car_number must be 4 digits + 3 uppercase letters (e.g. '1234ERS'), "
            f"got: {req.car_number!r}"
        )
    if not isinstance(req.date_of_birth, int) or not _RE_DOB.match(str(req.date_of_birth)):
        errors.append(
            f"date_of_birth must be an 8-digit integer YYYYMMDD, got: {req.date_of_birth!r}"
        )
    if not isinstance(req.registration_date, str) or not req.registration_date.strip():
        errors.append("registration_date is required (ISO 8601 string)")

    for name, val in [
        ("identity_type_id",        req.identity_type_id),
        ("nationality_id",           req.nationality_id),
        ("region_id",                req.region_id),
        ("city_id",                  req.city_id),
        ("car_type_id",              req.car_type_id),
        ("vehicle_sequence_number",  req.vehicle_sequence_number),
    ]:
        if not val or not str(val).strip():
            errors.append(f"{name} is required")

    if errors:
        raise ValueError("DriverRequest validation failed:\n  • " + "\n  • ".join(errors))


# ─── Service ───────────────────────────────────────────────────────────────────

class DriverService:
    """
    Manage drivers on the Tawseel platform.

    Usage::

        svc = DriverService()

        # Register a new driver
        driver = svc.create(DriverRequest(
            id_number="1234567890",
            identity_type_id="1",
            nationality_id="113",
            region_id="1",
            city_id="3",
            car_type_id="2",
            mobile="0512345678",
            car_number="1234ERS",
            date_of_birth=19900419,              # integer YYYYMMDD
            registration_date="2020-04-03T08:07:40.213Z",
            vehicle_sequence_number="123456789",
        ))

        # IMPORTANT: save driver.refrence_code — needed for edit
        print(driver.refrence_code)

        # Edit driver (refrence_code required)
        svc.update(DriverRequest(..., refrence_code=driver.refrence_code))

        # Get driver info
        info = svc.get("1234567890")

        # Deactivate
        svc.deactivate("1234567890")
    """

    def __init__(self, client: TawseelClient | None = None) -> None:
        self._client = client or TawseelClient()

    def create(self, req: DriverRequest) -> DriverInfo:
        """
        Register a new driver.
        Returns DriverInfo — PERSIST refrence_code for future edits.
        Raises DriverAlreadyExist (47) if already registered.
        """
        data = self._client.post(
            "/external/api/driver/create",
            payload=req.to_create_payload(),
        )
        return DriverInfo.from_api(data or {})

    def update(self, req: DriverRequest) -> DriverInfo:
        """
        Edit an existing driver. req.refrence_code is mandatory.
        """
        data = self._client.post(
            "/external/api/driver/edit",
            payload=req.to_edit_payload(),
        )
        return DriverInfo.from_api(data or {})

    def deactivate(self, id_number: str) -> bool:
        """
        Deactivate a driver by their national ID / Iqama number.
        Returns True on success.
        """
        if not id_number or not _RE_ID_NUMBER.match(id_number):
            raise ValueError("id_number must be 10 digits starting with 1 or 2")
        self._client.post(f"/external/api/driver/deactivate/{id_number}", payload={})
        return True

    def get(self, id_number: str) -> DriverInfo:
        """Fetch a driver's full profile by national ID / Iqama number."""
        if not id_number:
            raise ValueError("id_number is required")
        data = self._client.get(f"/external/api/driver/{id_number}")
        return DriverInfo.from_api(data or {})
