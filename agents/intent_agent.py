"""Intent Classifier & Response Generator Agent — Module 5.

STOP-ON-REPLY RULE: any inbound message first transitions the prospect to
REPLIED. Because the follow-up engine only ever targets OUTREACH_SENT /
FOLLOWING_UP states, the state machine itself is the kill-switch — no
scheduled follow-up can ever fire after a reply (see followup_agent).

Intent branches:
  DECLINED           -> OPT_OUT + polite farewell (automated)
  REQUEST_MORE_INFO  -> auto-reply from sponsorship knowledge base
                        (confidence < 0.75 => also flagged for human review)
  COMPLEX_QUESTION   -> needs_human_intervention = True, no auto-reply
  INTERESTED         -> reply with scheduling link => MEETING_PROPOSED
"""
from __future__ import annotations

import json
from pathlib import Path
from typing import Optional

from sqlalchemy.orm import Session

from agents.llm_client import IntentOutput, generate
from config import CALENDLY_LINK, llm_configured
from database import db_session
from database.models import InvalidTransition, Prospect, Sender, Status
from drivers.linkedin_base import InboundMessage, LinkedInProvider

_KB_PATH = Path(__file__).resolve().parent.parent / "data" / "knowledge_base.json"


def load_kb() -> dict:
    with open(_KB_PATH, "r", encoding="utf-8") as f:
        return json.load(f)


def classify(text: str) -> IntentOutput:
    return generate(
        prompt=text,
        schema=IntentOutput,
        system=(
            "Classify a LinkedIn reply to a hackathon sponsorship outreach into one "
            "of: DECLINED, REQUEST_MORE_INFO, COMPLEX_QUESTION, INTERESTED, "
            "NEUTRAL_ACK. Prefer DECLINED for explicit refusals or opt-outs; "
            "INTERESTED only for clear positive interest or meeting requests; "
            "COMPLEX_QUESTION for negotiations, procurement, ROI or multi-part "
            "questions a human should handle."
        ),
    )


def process_inbound(session: Session, msg: InboundMessage) -> Optional[Prospect]:
    """Handle one inbound message end-to-end. Returns the prospect or None."""
    prospect = db_session.find_prospect_by_email_or_name(
        session, email=msg.prospect_email, name=msg.prospect_name
    )
    if prospect is None:
        db_session.log_audit(
            session, event="unmatched_inbound",
            detail=f"No prospect match for {msg.prospect_email or msg.prospect_name!r}",
        )
        return None

    # ── STOP ON REPLY: enter REPLIED hub; follow-ups are now impossible ──
    db_session.log_message(
        session, prospect.id, Sender.PROSPECT, msg.text, intent=None, is_automated=False
    )
    if prospect.status in (Status.OUTREACH_SENT, Status.FOLLOWING_UP):
        prospect.set_status(Status.REPLIED)
        db_session.log_audit(
            session, event="followups_cancelled_on_reply", prospect_id=prospect.id,
            detail="Automated follow-ups halted (STOP-ON-REPLY rule).",
        )
    elif prospect.status != Status.REPLIED:
        # Replied again after MEETING_PROPOSED/CONFIRMED/INTERESTED — return to
        # the REPLIED hub so the classifier can route the new message.
        # Terminal states (OPT_OUT/REJECTED) accept no transitions: keep them
        # there permanently, but still classify + log the late reply.
        try:
            prospect.set_status(Status.REPLIED)
        except InvalidTransition:
            db_session.log_audit(
                session, event="late_reply_in_terminal_state",
                prospect_id=prospect.id,
                detail=f"Reply received while {prospect.status.value}; "
                       f"no status change (opt-out is permanent).",
            )
            verdict = classify(msg.text)
            last = db_session.get_messages(session, prospect.id)
            if last:
                last[-1].intent_detected = verdict.intent
            db_session.log_audit(
                session, event="reply_classified", prospect_id=prospect.id,
                detail=f"intent={verdict.intent} (no state change)",
            )
            return prospect

    verdict = classify(msg.text)
    # attach intent to the prospect's message row
    last = db_session.get_messages(session, prospect.id)
    if last:
        last[-1].intent_detected = verdict.intent

    handler = {
        "DECLINED": _handle_declined,
        "REQUEST_MORE_INFO": _handle_more_info,
        "COMPLEX_QUESTION": _handle_complex,
        "INTERESTED": _handle_interested,
    }.get(verdict.intent, _handle_neutral)
    handler(session, prospect, verdict, msg)

    db_session.log_audit(
        session, event="reply_classified", prospect_id=prospect.id,
        detail=f"intent={verdict.intent} confidence={verdict.confidence:.2f}",
    )
    session.flush()
    return prospect


def poll_replies(session: Session, driver: LinkedInProvider) -> int:
    """Pull all pending inbound messages from the driver and process them."""
    scan = driver.check_replies()
    n = 0
    for msg in scan.items:
        if process_inbound(session, msg) is not None:
            n += 1
    return n


# ─────────────────────────── intent handlers ───────────────────────────────
def _farewell(text: str) -> str:
    return (
        "Understood — thanks for letting me know, and no further messages from us. "
        "Wishing your team a great quarter ahead!"
    ) if text else ""


def _handle_declined(session: Session, p: Prospect, v: IntentOutput, msg: InboundMessage) -> None:
    p.set_status(Status.OPT_OUT)
    p.needs_human_intervention = False
    db_session.log_message(
        session, p.id, Sender.SYSTEM, _farewell(msg.text), intent="DECLINED",
        is_automated=True,
    )


def _handle_more_info(session: Session, p: Prospect, v: IntentOutput, msg: InboundMessage) -> None:
    kb = load_kb()
    ev = kb["event"]
    tiers = " | ".join(
        f"{t['tier']} SGD {t['amount_sgd']:,}" for t in kb["packages"]
    )
    inkind = "; ".join(kb["in_kind_options"])
    reply = (
        f"Great question! {ev['name']} runs {ev['dates']} ({ev['format']}), bringing "
        f"together {ev['audience']}. Sponsorship options: {tiers}. In-kind options: "
        f"{inkind}. Happy to send the full deck — or grab a slot here: {CALENDLY_LINK}"
    )
    db_session.log_message(
        session, p.id, Sender.SYSTEM, reply, intent="REQUEST_MORE_INFO", is_automated=True
    )
    if v.confidence < 0.75:
        p.needs_human_intervention = True


def _handle_complex(session: Session, p: Prospect, v: IntentOutput, msg: InboundMessage) -> None:
    p.needs_human_intervention = True
    db_session.log_message(
        session, p.id, Sender.SYSTEM,
        "[HUMAN REVIEW REQUIRED] Complex question/negotiation detected — no automated "
        "reply sent. Please respond manually from the dashboard.",
        intent="COMPLEX_QUESTION", is_automated=True,
    )


def _handle_interested(session: Session, p: Prospect, v: IntentOutput, msg: InboundMessage) -> None:
    if p.status in (Status.REPLIED, Status.INTERESTED):
        p.set_status(Status.INTERESTED)
    reply = (
        "Fantastic — excited to explore this! You can pick any time that suits you "
        f"here: {CALENDLY_LINK} . Once you book, it lands straight on our calendar "
        "and I'll send the sponsorship deck beforehand."
    )
    db_session.log_message(
        session, p.id, Sender.SYSTEM, reply, intent="INTERESTED", is_automated=True
    )
    # Scheduling link has been SENT => MEETING_PROPOSED (not confirmed!).
    p.set_status(Status.MEETING_PROPOSED)


def _handle_neutral(session: Session, p: Prospect, v: IntentOutput, msg: InboundMessage) -> None:
    # e.g. "Thanks!" — keep human in the loop cadence; no automated reply.
    db_session.log_message(
        session, p.id, Sender.SYSTEM,
        "[NEUTRAL_ACK] No automated reply triggered.", intent="NEUTRAL_ACK",
        is_automated=True,
    )
