# Tawseel TGA Bridge — ربط Tookan بمنصة Tawseel

نظام وسيط يربط منصة **Tookan** بمنصة **Tawseel** الحكومية (TGA/ELM) بشكل تلقائي كامل.

---

## كيف يعمل / How it works

```
تطبيق العميل (Tookan)
        ↓
  webhook_server.py   ←  يستقبل كل تغيير في حالة الطلب
        ↓
    Tawseel API       ←  يسجل الطلب / السائق / الموقع تلقائياً
```

---

## المتطلبات / Requirements

```
Python 3.10+
flask
requests
urllib3
openpyxl
```

تثبيت / Install:
```bash
pip install -r requirements.txt
```

---

## المتغيرات البيئية / Environment Variables

```
TOOKAN_API_KEY=your_tookan_api_key
TAWSEEL_REGION_ID=NV25GlPuOnQ=
TAWSEEL_CITY_ID=NV25GlPuOnQ=
TAWSEEL_CATEGORY_ID=NV25GlPuOnQ=
TAWSEEL_AUTHORITY_ID=NV25GlPuOnQ=
TAWSEEL_PAYMENT_METHOD_ID=NV25GlPuOnQ=
TAWSEEL_CANCEL_REASON_ID=NV25GlPuOnQ=
PORT=8080
```

---

## تشغيل السيرفر / Run

```bash
python webhook_server.py
```

---

## ربط Tookan / Tookan Setup

في إعدادات Tookan:
```
Settings → Notifications → Webhook URL
```
حط رابط السيرفر:
```
https://YOUR_SERVER_URL/webhook/tookan
```

---

## الملفات / Files

| الملف | الوظيفة |
|-------|--------|
| `webhook_server.py` | الخادم الرئيسي |
| `tawseel/bridge.py` | منطق الربط |
| `tawseel/orders.py` | إدارة الطلبات |
| `tawseel/drivers.py` | إدارة السائقين |
| `tawseel/location_tracker.py` | تتبع الموقع كل 15 ثانية |
| `tawseel/config.py` | الإعدادات |

---

## ملاحظة / Note

البيئة الحالية: **Sandbox (اختبار)**  
للتحويل للإنتاج: غيّر `ACTIVE_ENV = Environment.PRODUCTION` في `tawseel/config.py`
