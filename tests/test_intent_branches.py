"""Intent-agent branch coverage the smoke test never proves:

* COMPLEX_QUESTION  -> needs_human_intervention=True, automation paused,
  no transition past REPLIED, explicit "[HUMAN REVIEW REQUIRED]" notice.
* REQUEST_MORE_INFO -> knowledge-base auto-reply; low classifier confidence
  (< 0.75) additionally flags the prospect for human review; high confidence
  does not.
"""
import pytest

from agents import intent_agent
from agents.llm_client import IntentOutput
from database import db_session
from database.models import Status


def _reply_and_process(driver, session_factory, pid, email, name, text):
    """Queue one inbound reply through the real poll/classify pipeline."""
    driver.queue_inbound(email, name, text)
    with session_factory() as s:
        n = intent_agent.poll_replies(s, driver)
        p = db_session.get_prospect(s, pid)
        return n, p


def _last_system_message(session_factory, pid):
    with session_factory() as s:
        msgs = db_session.get_messages(s, pid)
        return [m for m in msgs if m.sender.value == "SYSTEM"][-1]


# ───────────────────── COMPLEX_QUESTION branch ──────────────────────────────
def test_complex_question_flags_human_and_holds_state(
    session_factory, driver, sent_prospect
):
    pid, email, name = sent_prospect

    # Sanity: outreach actually went out through the real pipeline.
    with session_factory() as s:
        p = db_session.get_prospect(s, pid)
        assert p.status == Status.OUTREACH_SENT

    n, p = _reply_and_process(
        driver, session_factory, pid, email, name,
        "What ROI did prior sponsors see, and can you do better on the SGD 25k "
        "Titanium tier? Procurement closes in Q3 — who owns budget sign-off?",
    )

    assert n == 1
    assert p.status == Status.REPLIED, (
        f"complex question must hold at REPLIED, got {p.status.value}"
    )
    assert p.needs_human_intervention is True, "automation must pause for a human"

    notice = _last_system_message(session_factory, pid)
    assert notice.intent_detected == "COMPLEX_QUESTION"
    assert "[HUMAN REVIEW REQUIRED]" in notice.content
    assert notice.is_automated is True

    # Automation stays paused on a later pass too.
    from agents import followup_agent
    with session_factory() as s:
        camp = db_session.get_or_create_campaign(s)
        camp.delay_days = 0
        assert followup_agent.run_followups(s, camp, driver) == 0


# ─────────────────── REQUEST_MORE_INFO confidence gate ──────────────────────
def test_more_info_low_confidence_flags_human(
    session_factory, driver, sent_prospect, monkeypatch
):
    pid, email, name = sent_prospect

    real_classify = intent_agent.classify

    def fake_classify(text):
        verdict = real_classify(text)
        return IntentOutput(
            intent=verdict.intent, confidence=0.4, reasoning="forced-low"
        )

    monkeypatch.setattr(intent_agent, "classify", fake_classify)

    n, p = _reply_and_process(
        driver, session_factory, pid, email, name,
        "What does sponsorship involve exactly?",
    )

    assert n == 1
    assert p.status == Status.REPLIED, (
        f"more-info keeps REPLIED, got {p.status.value}"
    )
    assert p.needs_human_intervention is True, (
        "confidence < 0.75 must flag for human review"
    )

    reply = _last_system_message(session_factory, pid)
    assert reply.intent_detected == "REQUEST_MORE_INFO"
    # Knowledge-base auto-reply still went out with real package data.
    assert "SGD" in reply.content and "Happy to send the full deck" in reply.content


def test_more_info_high_confidence_no_flag(
    session_factory, driver, sent_prospect
):
    pid, email, name = sent_prospect

    n, p = _reply_and_process(
        driver, session_factory, pid, email, name,
        "What does sponsorship involve exactly?",
    )

    assert n == 1
    assert p.status == Status.REPLIED
    assert p.needs_human_intervention is False, (
        "confidence >= 0.75 must NOT flag for human review"
    )

    reply = _last_system_message(session_factory, pid)
    assert reply.intent_detected == "REQUEST_MORE_INFO"
    assert "SGD" in reply.content
