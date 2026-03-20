"""
Micro-service SMS pour l'option B (webhook).
Logement Facile envoie POST JSON {"to", "message"} vers SMS_DISPATCH_URL = https://ton-dispatcher.onrender.com/dispatch

Variables d'environnement : voir README.md dans ce dossier.
"""
from __future__ import annotations

import base64
import logging
import os
import sys

from flask import Flask, jsonify, request

logging.basicConfig(level=logging.INFO, stream=sys.stdout)
log = logging.getLogger("sms-dispatcher")

app = Flask(__name__)


def _check_bearer() -> bool:
    token = (os.environ.get("DISPATCH_BEARER_TOKEN") or "").strip()
    if not token:
        return True
    auth = request.headers.get("Authorization") or ""
    expected = f"Bearer {token}"
    return auth.strip() == expected


def _send_twilio(to: str, body: str) -> tuple[bool, str]:
    import requests

    sid = (os.environ.get("TWILIO_ACCOUNT_SID") or "").strip()
    tok = (os.environ.get("TWILIO_AUTH_TOKEN") or "").strip()
    frm = (os.environ.get("TWILIO_FROM") or os.environ.get("TWILIO_PHONE_NUMBER") or "").strip()
    if not (sid and tok and frm):
        return False, "Twilio incomplet"
    url = f"https://api.twilio.com/2010-04-01/Accounts/{sid}/Messages.json"
    auth_b64 = base64.b64encode(f"{sid}:{tok}".encode()).decode()
    r = requests.post(
        url,
        data={"To": to, "From": frm, "Body": body},
        headers={
            "Authorization": f"Basic {auth_b64}",
            "Content-Type": "application/x-www-form-urlencoded",
        },
        timeout=30,
    )
    if 200 <= r.status_code < 300:
        return True, "twilio_ok"
    return False, f"twilio_http_{r.status_code}"


def _forward_upstream(to: str, message: str) -> tuple[bool, str]:
    import requests

    up = (os.environ.get("SMS_UPSTREAM_URL") or "").strip()
    if not up:
        return False, "no_upstream"
    headers = {"Content-Type": "application/json"}
    extra = (os.environ.get("SMS_UPSTREAM_AUTH_HEADER") or "").strip()
    if extra:
        # ex: "Authorization: Bearer xyz" ou "X-Api-Key: abc"
        if ":" in extra:
            k, v = extra.split(":", 1)
            headers[k.strip()] = v.strip()
    r = requests.post(up, json={"to": to, "message": message}, headers=headers, timeout=30)
    if 200 <= r.status_code < 300:
        return True, "upstream_ok"
    return False, f"upstream_http_{r.status_code}"


@app.get("/health")
def health():
    return jsonify({"ok": True, "service": "sms-dispatcher"}), 200


@app.post("/dispatch")
def dispatch():
    if not _check_bearer():
        log.warning("unauthorized dispatch attempt")
        return jsonify({"ok": False, "error": "unauthorized"}), 401

    if not request.is_json:
        return jsonify({"ok": False, "error": "json_required"}), 400

    data = request.get_json(silent=True) or {}
    to = (data.get("to") or "").strip()
    message = (data.get("message") or "").strip()
    if not to or not message:
        return jsonify({"ok": False, "error": "to_and_message_required"}), 400

    mode = (os.environ.get("SMS_MODE") or "auto").strip().lower()

    ok, detail = False, ""
    tried_twilio = False
    tried_upstream = False

    if mode == "echo":
        log.info("SMS echo to=%s len=%s", to, len(message))
        return jsonify({"ok": True, "mode": "echo", "detail": "logged_only"}), 200

    use_twilio = mode == "twilio" or (
        mode == "auto" and (os.environ.get("TWILIO_ACCOUNT_SID") or "").strip()
    )
    if use_twilio:
        tried_twilio = True
        ok, detail = _send_twilio(to, message)
        if ok:
            log.info("SMS sent via twilio to=%s", to)
            return jsonify({"ok": True, "mode": "twilio", "detail": detail}), 200
        if mode == "twilio":
            log.error("twilio failed: %s", detail)
            return jsonify({"ok": False, "error": detail}), 502

    use_upstream = mode == "upstream" or (
        mode == "auto" and (os.environ.get("SMS_UPSTREAM_URL") or "").strip()
    )
    if use_upstream:
        tried_upstream = True
        ok, detail = _forward_upstream(to, message)
        if ok:
            log.info("SMS forwarded to=%s", to)
            return jsonify({"ok": True, "mode": "upstream", "detail": detail}), 200
        if mode == "upstream":
            log.error("upstream failed: %s", detail)
            return jsonify({"ok": False, "error": detail}), 502

    if mode == "auto" and (tried_twilio or tried_upstream):
        log.error("SMS send failed after provider attempt: %s", detail)
        return jsonify({"ok": False, "error": detail or "send_failed"}), 502

    if mode == "auto":
        log.warning("SMS_MODE=auto but no Twilio nor SMS_UPSTREAM — echo fallback")
        log.info("SMS would send to=%s preview=%s...", to, message[:80])
        return jsonify({"ok": True, "mode": "echo_fallback", "detail": "configure_twilio_or_upstream"}), 200

    return jsonify({"ok": False, "error": "unknown_sms_mode"}), 500


if __name__ == "__main__":
    port = int(os.environ.get("PORT", "5001"))
    app.run(host="0.0.0.0", port=port, debug=False)
