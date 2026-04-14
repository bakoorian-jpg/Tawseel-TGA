"""
lookups.py — Lookup Service مع TTL Cache
Fetches all reference data (regions, cities, nationalities, car types, etc.)
and caches results in memory to avoid repeated network calls.

Endpoint base: /external/api/lookup/
Response format: { "data": [...], "errorCodes": [0], "status": true }
Each item: { "id": "...", "nameAr": "...", "nameEn": "..." }
"""

from __future__ import annotations

import threading
import time
from dataclasses import dataclass
from typing import Any

from .base_client import TawseelClient
from .config import LOOKUP_CACHE_TTL_HOURS

_TTL_SECONDS = LOOKUP_CACHE_TTL_HOURS * 3600
_BASE = "/external/api/lookup"


@dataclass(frozen=True)
class LookupItem:
    """A single entry from any lookup list."""
    id: str
    name_ar: str
    name_en: str

    def __str__(self) -> str:
        return f"{self.id} — {self.name_en} / {self.name_ar}"


@dataclass
class _CacheEntry:
    data: list[LookupItem]
    expires_at: float


class LookupService:
    """
    Fetches and caches all TGA lookup tables.

    All lookup calls are thread-safe. Results are cached for
    LOOKUP_CACHE_TTL_HOURS (default 24 h) and refreshed lazily on next access.

    Usage::

        svc = LookupService()

        regions    = svc.regions()
        cities     = svc.cities("1")          # pass region id
        nat        = svc.nationalities()      # countries list
        car_types  = svc.car_types()
        categories = svc.order_categories()
        id_types   = svc.identity_types()
        pay_methods= svc.payment_methods()
        authorities= svc.authorities()
        reasons    = svc.cancel_reasons()

        # Find by name
        riyadh = svc.find_city("1", name_en="Riyadh")
        print(riyadh.id)
    """

    def __init__(self, client: TawseelClient | None = None) -> None:
        self._client = client or TawseelClient()
        self._lock = threading.Lock()
        self._cache: dict[str, _CacheEntry] = {}

    # ── Lookup endpoints ────────────────────────────────────────────────────────

    def regions(self) -> list[LookupItem]:
        """المناطق الإدارية في المملكة."""
        return self._fetch("regions", f"{_BASE}/regions-list")

    def cities(self, region_id: str) -> list[LookupItem]:
        """مدن منطقة معينة."""
        if not region_id or not str(region_id).strip():
            raise ValueError("region_id is required")
        return self._fetch(f"cities_{region_id}", f"{_BASE}/{region_id}/cities-list")

    def nationalities(self) -> list[LookupItem]:
        """الجنسيات / الدول (countries list)."""
        return self._fetch("nationalities", f"{_BASE}/countries-list")

    def identity_types(self) -> list[LookupItem]:
        """أنواع الهوية (وطنية / إقامة / جواز)."""
        return self._fetch("identity_types", f"{_BASE}/identity-types-list")

    def car_types(self) -> list[LookupItem]:
        """أنواع المركبات."""
        return self._fetch("car_types", f"{_BASE}/car-types-list")

    def order_categories(self) -> list[LookupItem]:
        """تصنيفات الطلبات."""
        return self._fetch("order_categories", f"{_BASE}/categories-list")

    def authorities(self) -> list[LookupItem]:
        """الجهات الحكومية (للطلبات الرسمية)."""
        return self._fetch("authorities", f"{_BASE}/authorities-list")

    def cancel_reasons(self) -> list[LookupItem]:
        """أسباب إلغاء الطلب."""
        return self._fetch("cancel_reasons", f"{_BASE}/cancellation-reasons-list")

    def payment_methods(self) -> list[LookupItem]:
        """طرق الدفع (مطلوبة عند تنفيذ الطلب)."""
        return self._fetch("payment_methods", f"{_BASE}/payment-methods-list")

    # ── Convenience finders ─────────────────────────────────────────────────────

    def find_region(
        self, *, id: str | None = None, name_en: str | None = None, name_ar: str | None = None
    ) -> LookupItem | None:
        return self._find(self.regions(), id=id, name_en=name_en, name_ar=name_ar)

    def find_city(
        self, region_id: str, *, id: str | None = None, name_en: str | None = None, name_ar: str | None = None
    ) -> LookupItem | None:
        return self._find(self.cities(region_id), id=id, name_en=name_en, name_ar=name_ar)

    def find_nationality(
        self, *, id: str | None = None, name_en: str | None = None, name_ar: str | None = None
    ) -> LookupItem | None:
        return self._find(self.nationalities(), id=id, name_en=name_en, name_ar=name_ar)

    def find_car_type(
        self, *, id: str | None = None, name_en: str | None = None, name_ar: str | None = None
    ) -> LookupItem | None:
        return self._find(self.car_types(), id=id, name_en=name_en, name_ar=name_ar)

    def find_order_category(
        self, *, id: str | None = None, name_en: str | None = None, name_ar: str | None = None
    ) -> LookupItem | None:
        return self._find(self.order_categories(), id=id, name_en=name_en, name_ar=name_ar)

    # ── Cache management ────────────────────────────────────────────────────────

    def invalidate(self, key: str | None = None) -> None:
        """Force cache refresh. Pass key to invalidate a specific entry, or None for all."""
        with self._lock:
            if key:
                self._cache.pop(key, None)
            else:
                self._cache.clear()

    # ── Internal helpers ────────────────────────────────────────────────────────

    def _fetch(self, cache_key: str, path: str) -> list[LookupItem]:
        now = time.monotonic()
        with self._lock:
            entry = self._cache.get(cache_key)
            if entry and now < entry.expires_at:
                return entry.data

        raw: list[dict[str, Any]] = self._client.get(path) or []
        # data field is a list of {"id": "...", "nameAr": "...", "nameEn": "..."}
        if isinstance(raw, dict):
            raw = raw.get("data") or []
        items = [
            LookupItem(
                id=str(r.get("id") or ""),
                name_ar=str(r.get("nameAr") or ""),
                name_en=str(r.get("nameEn") or ""),
            )
            for r in raw
        ]

        with self._lock:
            self._cache[cache_key] = _CacheEntry(
                data=items, expires_at=time.monotonic() + _TTL_SECONDS
            )
        return items

    @staticmethod
    def _find(
        items: list[LookupItem],
        *,
        id: str | None,
        name_en: str | None,
        name_ar: str | None,
    ) -> LookupItem | None:
        for item in items:
            if id is not None and item.id == str(id):
                return item
            if name_en is not None and item.name_en.lower() == name_en.lower():
                return item
            if name_ar is not None and item.name_ar == name_ar:
                return item
        return None
