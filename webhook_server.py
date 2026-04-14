"""
webhook_server.py — Webhook receiver for Tookan → Tawseel bridge
=================================================================

This is the HTTP server that Tookan will POST to whenever a task or
driver status changes. It translates those events into Tawseel API calls.

SETUP
-----
1. Fill in YOUR_TOOKAN_API_KEY and the Tawseel IDs below.
2. Install dependencies:
       pip install flask requests urllib3
3. Run:
       python webhook_server.py
4. Expose to the internet (ngrok for testing, or deploy to a VPS):
       ngrok http 5000
5. In Tookan dashboard → Settings → Notifications → Webhook URL:
       https://YOUR_URL/webhook/tookan

That's it. Every order in Tookan now auto-syncs to Tawseel.

DRIVER SETUP NOTE
-----------------
For driver assignment to work, each driver's Saudi National ID (or Iqama)
must be stored in Tookan's "License" field on their agent profile.
The bridge reads it from there.
"""

import atexit
import logging
import os

from flask import Flask, jsonify, request

from tawseel.bridge import BridgeConfig, TookanTawseelBridge
from tawseel.config import ACTIVE_ENV, Environment

# ── Logging ────────────────────────────────────────────────────────────────────
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s  %(levelname)-8s  %(name)s — %(message)s",
)
logger = logging.getLogger("webhook_server")

# ── Configuration — FILL THESE IN ─────────────────────────────────────────────
TOOKAN_API_KEY = os.getenv("TOOKAN_API_KEY", "LFAD_$2a$10$FwmpniaAM/Z8qannUBAkvONXbadaeim8i1AFFsNTZP9rOED13gRlu_HIPPO")

# Get these IDs by running: python -m tawseel.main (or check lookups manually)
TAWSEEL_CONFIG = BridgeConfig(
    # IDs from sandbox lookups (base64-encoded by Tawseel API)
    # NV25GlPuOnQ= = Riyadh region / Riyadh city / Food / Cash / Restaurant / "From Customer"
    region_id          = os.getenv("TAWSEEL_REGION_ID",          "NV25GlPuOnQ="),  # Riyadh
    city_id            = os.getenv("TAWSEEL_CITY_ID",            "NV25GlPuOnQ="),  # Riyadh
    category_id        = os.getenv("TAWSEEL_CATEGORY_ID",        "NV25GlPuOnQ="),  # Food
    authority_id       = os.getenv("TAWSEEL_AUTHORITY_ID",       "NV25GlPuOnQ="),  # Restaurant
    payment_method_id  = os.getenv("TAWSEEL_PAYMENT_METHOD_ID",  "NV25GlPuOnQ="),  # Cash
    cancel_reason_id   = os.getenv("TAWSEEL_CANCEL_REASON_ID",   "NV25GlPuOnQ="),  # From Customer
    driver_income_ratio= 0.7,   # driver gets 70% of delivery fee
)

# ── App setup ──────────────────────────────────────────────────────────────────
app    = Flask(__name__)
bridge = TookanTawseelBridge(
    tookan_api_key=TOOKAN_API_KEY,
    config=TAWSEEL_CONFIG,
)

logger.info("Environment: %s", ACTIVE_ENV.value.upper())
logger.info("Bridge ready — location tracker running every 15s")

# Stop tracker cleanly on server shutdown
atexit.register(lambda: bridge._tracker.stop() if bridge._tracker else None)


# ── Routes ─────────────────────────────────────────────────────────────────────

@app.route("/webhook/tookan", methods=["POST"])
def tookan_webhook():
    """
    Tookan posts here on every task/agent status change.
    Configure this URL in: Tookan Dashboard → Settings → Notifications → Webhook URL
    """
    payload = request.get_json(force=True, silent=True)
    if not payload:
        logger.warning("Empty or non-JSON webhook received")
        return jsonify({"ok": False, "error": "empty payload"}), 400

    logger.info(
        "Webhook received — job_id=%s job_status=%s order_id=%s",
        payload.get("job_id"),
        payload.get("job_status"),
        payload.get("order_id"),
    )

    result = bridge.handle_webhook(payload)
    logger.info("Bridge result: %s", result)

    return jsonify({
        "ok":           result.success,
        "action":       result.action_taken,
        "tawseel_ref":  result.tawseel_ref,
        "error":        result.error,
    }), 200


@app.route("/health", methods=["GET"])
def health():
    """Health check endpoint — returns 200 if server is running."""
    return jsonify({
        "status":      "ok",
        "environment": ACTIVE_ENV.value,
    }), 200


@app.route("/", methods=["GET"])
def index():
    return jsonify({
        "service": "Tookan → Tawseel Bridge",
        "version": "1.0",
        "webhook": "/webhook/tookan  [POST]",
        "health":  "/health          [GET]",
    }), 200


# ── Entry point ────────────────────────────────────────────────────────────────

if __name__ == "__main__":
    port = int(os.getenv("PORT", 5000))
    debug = ACTIVE_ENV == Environment.TEST
    logger.info("Starting server on port %d (debug=%s)", port, debug)
    app.run(host="0.0.0.0", port=port, debug=debug)
