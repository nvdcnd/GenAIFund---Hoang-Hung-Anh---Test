"""Cal.com / Calendly booking webhook listener — Module 6.

Runs as a small FastAPI service (default http://127.0.0.1:8001) alongside the
Streamlit dashboard. The dashboard also exposes a one-click "Simulate Cal.com
Webhook" button that calls the same core function, so evaluators can test
meeting conversion without running the API server.

CRITICAL RULE ENFORCED HERE:
  MEETING_PROPOSED -> MEETING_CONFIRMED happens ONLY when a webhook payload
  is received (or its exact simulator invoked). Nothing else may confirm.
"""
from __future__ import annotations

import hmac
import hashlib
import json
from contextlib import asynccontextmanager
from typing import Any, Optional

from fastapi import FastAPI, Header, HTTPException, Request
from sqlalchemy import select

from config import API_HOST, API_PORT, WEBHOOK_SECRET
from database import db_session
from database.models import Prospect, Status

app = FastAPI(title="GenAI Fund Outreach — Webhook Listener", version="1.0.0")


# ─────────────────────────── core processing ───────────────────────────────
def process_booking(payload: dict) -> dict:
    """Match a booking payload to a prospect and confirm the meeting.

    Supports Cal.com and Calendly webhook shapes; matches on email first,
    then on name. Idempotent: repeat webhooks are safe.
    """
    email, name, event_type = _extract_identity(payload)
    with db_session.session_scope() as session:
        prospect = db_session.find_prospect_by_email_or_name(session, email=email, name=name)
        if prospect is None:
            db_session.log_audit(
                session, event="booking_unmatched",
                detail=f"email={email!r} name={name!r}",
            )
            raise HTTPException(status_code=404, detail="No matching prospect")

        if prospect.status == Status.MEETING_CONFIRMED:
            return {"ok": True, "prospect_id": prospect.id,
                    "status": prospect.status.value, "idempotent": True}

        if prospect.status != Status.MEETING_PROPOSED:
            # Require the proper funnel order (link must have been sent).
            raise HTTPException(
                status_code=409,
                detail=(
                    f"Prospect status is {prospect.status.value}; expected "
                    f"MEETING_PROPOSED before a booking can be confirmed."
                ),
            )

        prospect.set_status(Status.MEETING_CONFIRMED)
        db_session.log_audit(
            session, event="meeting_confirmed_webhook", prospect_id=prospect.id,
            detail=f"source=webhook email={email!r} name={name!r}",
        )
        pid = prospect.id
    return {"ok": True, "prospect_id": pid, "status": Status.MEETING_CONFIRMED.value}


def _extract_identity(payload: dict) -> tuple[str, str, str]:
    """Pull (email, name, event_type) from Cal.com or Calendly payloads."""
    def dig(d: dict, *keys: str) -> Any:
        cur: Any = d
        for k in keys:
            if not isinstance(cur, dict):
                return None
            cur = cur.get(k)
        return cur

    email = (
        dig(payload, "payload", "email") or dig(payload, "data", "payload", "email")
        or dig(payload, "data", "email") or payload.get("email") or ""
    )
    name = (
        dig(payload, "payload", "name") or dig(payload, "data", "payload", "name")
        or dig(payload, "data", "name") or payload.get("name") or ""
    )
    event_type = (
        dig(payload, "payload", "event_type") or dig(payload, "payload", "eventType")
        or payload.get("event_type") or payload.get("eventType") or ""
    )
    return str(email).strip().lower(), str(name).strip(), str(event_type)


# ───────────────────────────── FastAPI routes ──────────────────────────────
@app.get("/health")
def health() -> dict:
    return {"ok": True, "service": "webhook-listener"}


@app.post("/api/webhook/booking")
async def booking_webhook(request: Request,
                          x_webhook_secret: Optional[str] = Header(default=None)) -> dict:
    raw = await request.body()
    if WEBHOOK_SECRET and WEBHOOK_SECRET != "change-me":
        supplied = request.headers.get("X-Webhook-Secret", "")
        expected = hmac.new(WEBHOOK_SECRET.encode(), raw, hashlib.sha256).hexdigest()
        # accept either the raw secret (simple mode) or HMAC signature
        if supplied not in (WEBHOOK_SECRET, expected):
            raise HTTPException(status_code=401, detail="Invalid webhook secret")
    try:
        payload = json.loads(raw or b"{}")
    except json.JSONDecodeError:
        raise HTTPException(status_code=400, detail="Invalid JSON")

    result = process_booking(payload)
    return {"received": True, **result}


@app.post("/api/webhook/booking/simulate")
def simulate_booking(email: str = "", name: str = "") -> dict:
    """Test helper: fabricates a Cal.com-shaped payload for the given prospect."""
    payload = {
        "event": "booking.created",
        "payload": {
            "email": email or None,
            "name": name or None,
            "event_type": "hackathon-sponsor-intro",
        },
    }
    if not (email or name):
        raise HTTPException(status_code=400, detail="email or name required")
    return process_booking(payload)
