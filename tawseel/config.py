"""
config.py — إعدادات التكامل مع منصة Tawseel (TGA)
Configuration for Tawseel / Logisti API Integration
"""

from enum import Enum


class Environment(Enum):
    TEST = "test"
    PRODUCTION = "production"


# ─── بيئة التشغيل الحالية ───────────────────────────────────────────────────
ACTIVE_ENV = Environment.TEST  # غيّرها إلى PRODUCTION عند الإطلاق الفعلي


# ─── بيانات الاعتماد ─────────────────────────────────────────────────────────
CREDENTIALS = {
    Environment.TEST: {
        "app_id":  "6504a146",
        "app_key": "5e1ba8a29127eb21160a07ef3259ee83",
        "base_url": "https://tawseel-stg.api.elm.sa",
    },
    Environment.PRODUCTION: {
        "app_id":  "",        # تُعطى من ELM بعد اجتياز الاختبار
        "app_key": "",        # تُعطى من ELM بعد اجتياز الاختبار
        "base_url": "https://tawseel.api.elm.sa",
    },
}

# ─── إعدادات Recovery (مختلفة عن الرئيسية) ──────────────────────────────────
RECOVERY = {
    Environment.TEST: {
        "base_url":      "https://demo-apitawseel.naql.sa",
        "company_name":  "",   # يُطلب من ELM
        "password":      "",   # يُطلب من ELM
    },
    Environment.PRODUCTION: {
        "base_url":      "https://tawseelapi.ecloud.sa",
        "company_name":  "",
        "password":      "",
    },
}

# ─── إعدادات الاتصال ─────────────────────────────────────────────────────────
TIMEOUT_SECONDS   = 30
MAX_RETRIES       = 3
BACKOFF_FACTOR    = 0.5   # ثانية × 2^(retry) بين كل محاولة

# ─── الـ Cache للـ Lookups ────────────────────────────────────────────────────
LOOKUP_CACHE_TTL_HOURS = 24


# ─── Helpers ─────────────────────────────────────────────────────────────────
def get_base_url() -> str:
    return CREDENTIALS[ACTIVE_ENV]["base_url"]


def get_app_id() -> str:
    return CREDENTIALS[ACTIVE_ENV]["app_id"]


def get_app_key() -> str:
    return CREDENTIALS[ACTIVE_ENV]["app_key"]


def get_recovery_config() -> dict:
    return RECOVERY[ACTIVE_ENV]


def get_headers() -> dict:
    """Headers مطلوبة في كل طلب للـ API الرئيسية."""
    return {
        "Content-Type": "application/json",
        "app-id":       get_app_id(),
        "app-key":      get_app_key(),
    }
