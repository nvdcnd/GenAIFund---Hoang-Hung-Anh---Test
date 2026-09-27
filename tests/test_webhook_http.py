"""HTTP-level Cal.com webhook tests: the real FastAPI app via TestClient.

Proves the transport contract, not just process_booking():
* secret enforcement (401 raw / 401 HMAC / 200 HMAC),
* 200 confirm only from MEETING_PROPOSED (409 otherwise),
* 404 unknown prospect, idempotent repeat webhook, invalid JSON -> 400.
"""
import hashlib
import hmac as hmac_mod

import pytest
from fastapi.testclient import TestClient

from database import db_session
from database.models import Status
from utils.webhook_handler import app

SECRET = "test-webhook-secret"  # matches tests/conftest.py env


@pytest.fixture(scope="module")
def client():
    # TransportTestClient runs the ASGI app in-process: same code path as
    # uvicorn minus the socket. The project router has no startup hooks that
    # depend on a live server.
    with TestClient(app) as c:
        yield c


def _hmac(raw: bytes) -> str:
    return hmac_mod.new(SECRET.encode(), raw, hashlib.sha256).hexdigest()


def _at_meeting_proposed(session_factory, driver, sent_prospect) -> int:
    """Drive the prospect through the real reply pipeline to MEETING_PROPOSED.

    The state machine forbids OUTREACH_SENT -> MEETING_PROPOSED directly, so
    tests reach it the way production does: interested reply -> scheduling link.
    """
    from agents import intent_agent

    pid, email, name = sent_prospect
    driver.queue_inbound(email, name, "We like this — how do we set up a call?")
    with session_factory() as s:
        intent_agent.poll_replies(s, driver)
        p = db_session.get_prospect(s, pid)
        assert p.status == Status.MEETING_PROPOSED
    return pid


def _booking_body(email: str, name: str) -> bytes:
    import json
    return json.dumps(
        {"payload": {"email": email, "name": name}}
    ).encode()


def _post(client, body: bytes, secret: str | None = None, signed: bool = False):
    headers = {"Content-Type": "application/json"}
    if signed:
        headers["X-Webhook-Secret"] = _hmac(body)
    elif secret is not None:
        headers["X-Webhook-Secret"] = secret
    return client.post(
        "/api/webhook/booking", content=body, headers=headers
    )


# ───────────────────────────── secret gate ──────────────────────────────────
def test_missing_secret_rejected_401(client):
    r = client.post(
        "/api/webhook/booking", content=_booking_body("x@y.example", "X"),
        headers={"Content-Type": "application/json"},
    )
    assert r.status_code == 401
    assert "secret" in r.json()["detail"].lower()


def test_wrong_secret_rejected_401(client):
    r = _post(client, _booking_body("x@y.example", "X"), secret="not-the-secret")
    assert r.status_code == 401


def test_hmac_signature_accepted_200(client, session_factory, driver, sent_prospect):
    """Real Cal.com-style HMAC signing must pass: status -> MEETING_CONFIRMED."""
    pid = _at_meeting_proposed(session_factory, driver, sent_prospect)
    email, name = sent_prospect[1], sent_prospect[2]

    body = _booking_body(email, name)
    r = _post(client, body, signed=True)
    assert r.status_code == 200
    data = r.json()
    assert data["received"] is True and data["ok"] is True
    assert data["prospect_id"] == pid
    assert data["status"] == "MEETING_CONFIRMED"

    with session_factory() as s:
        p = db_session.get_prospect(s, pid)
        assert p.status == Status.MEETING_CONFIRMED


def test_raw_secret_accepted_200(client, session_factory, driver, sent_prospect):
    """Simple mode: header carrying the raw shared secret also passes."""
    _at_meeting_proposed(session_factory, driver, sent_prospect)
    email, name = sent_prospect[1], sent_prospect[2]

    r = _post(client, _booking_body(email, name), secret=SECRET)
    assert r.status_code == 200
    assert r.json()["status"] == "MEETING_CONFIRMED"


# ───────────────────────── status-machine gate ──────────────────────────────
def test_confirm_from_wrong_status_rejected_409(
    client, session_factory, sent_prospect
):
    pid, email, name = sent_prospect
    # Prospect is OUTREACH_SENT here — link was never sent.
    r = _post(client, _booking_body(email, name), secret=SECRET)
    assert r.status_code == 409
    assert "MEETING_PROPOSED" in r.json()["detail"]


def test_unknown_prospect_404(client):
    r = _post(
        client,
        _booking_body("nobody@nowhere.example", "Nobody Nowhere"),
        secret=SECRET,
    )
    assert r.status_code == 404


def test_repeat_webhook_idempotent_200(
    client, session_factory, driver, sent_prospect
):
    pid = _at_meeting_proposed(session_factory, driver, sent_prospect)
    email, name = sent_prospect[1], sent_prospect[2]

    body = _booking_body(email, name)
    assert _post(client, body, secret=SECRET).status_code == 200
    r2 = _post(client, body, secret=SECRET)  # replay
    assert r2.status_code == 200
    assert r2.json().get("idempotent") is True
    with session_factory() as s:
        p = db_session.get_prospect(s, pid)
        assert p.status == Status.MEETING_CONFIRMED


def test_invalid_json_400(client):
    r = client.post(
        "/api/webhook/booking", content=b"{not json",
        headers={
            "Content-Type": "application/json",
            "X-Webhook-Secret": _hmac(b"{not json"),
        },
    )
    assert r.status_code == 400
