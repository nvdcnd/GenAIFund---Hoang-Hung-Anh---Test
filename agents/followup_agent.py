"""Outreach Execution & Smart Follow-Up Engine — Module 4.

* send_outreach(): first touch on approval (APPROVED -> OUTREACH_SENT).
* run_followups(): cron-style pass over prospects due for a follow-up.

Guarantees:
* STOP-ON-REPLY — prospects in REPLIED (or any downstream state: OPT_OUT,
  INTERESTED, MEETING_PROPOSED, MEETING_CONFIRMED) are structurally excluded
  because only OUTREACH_SENT / FOLLOWING_UP qualify.
* max_followups — enforced against the campaign config.
* cadence — a prospect is only touched after `delay_days` of inactivity.
* no duplicates — one message max per pass, and followup_count gating.
"""
from __future__ import annotations

from datetime import datetime, timezone

from sqlalchemy.orm import Session

from agents.llm_client import FollowupOutput, generate
from config import llm_configured
from database import db_session
from database.models import CampaignConfig, Prospect, Sender, Status
from drivers.linkedin_base import LinkedInProvider


def send_outreach(session: Session, prospect: Prospect, campaign: CampaignConfig,
                  driver: LinkedInProvider, text: str = "") -> bool:
    """Send the approved first-touch message and move to OUTREACH_SENT."""
    if prospect.status != Status.APPROVED:
        raise ValueError(
            f"Prospect {prospect.contact_name} must be APPROVED to send "
            f"(current: {prospect.status.value})."
        )
    message = text.strip() or prospect.draft_message
    result = driver.send_message(prospect, message)
    if not result.ok:
        db_session.log_audit(session, event="send_failed", prospect_id=prospect.id,
                             detail=result.note)
        return False

    db_session.log_message(
        session, prospect.id, Sender.SYSTEM, message,
        intent=None, is_automated=not text,  # manually edited => not 'automated'
    )
    prospect.set_status(Status.OUTREACH_SENT)
    prospect.last_activity_at = datetime.now(timezone.utc)
    db_session.log_audit(
        session, event="outreach_sent", prospect_id=prospect.id,
        detail=f"driver={result.driver} external_id={result.external_id} "
               f"simulated={result.simulated}",
    )
    session.flush()
    return True


def run_followups(session: Session, campaign: CampaignConfig,
                  driver: LinkedInProvider) -> int:
    """One cron pass: follow up every prospect whose cadence has elapsed."""
    due = [p for p in db_session.list_prospects(session)
           if db_session.is_followup_due(p, campaign.max_followups, campaign.delay_days)]

    sent = 0
    for p in due:
        # Re-check inside the loop: STOP-ON-REPLY may have fired mid-pass via
        # a concurrent reply scan; state machine is the source of truth.
        if p.status not in (Status.OUTREACH_SENT, Status.FOLLOWING_UP):
            continue
        if p.needs_human_intervention:
            continue

        message = _compose_followup(p, campaign)
        result = driver.send_message(p, message)
        if not result.ok:
            continue

        db_session.log_message(
            session, p.id, Sender.SYSTEM, message, intent="FOLLOWUP", is_automated=True
        )
        if p.status == Status.OUTREACH_SENT:
            p.set_status(Status.FOLLOWING_UP)
        p.followup_count += 1
        p.last_activity_at = datetime.now(timezone.utc)
        db_session.log_audit(
            session, event="followup_sent", prospect_id=p.id,
            detail=f"count={p.followup_count}/{campaign.max_followups} "
                   f"driver={result.driver}",
        )
        sent += 1

    session.flush()
    return sent


def _compose_followup(p: Prospect, campaign: CampaignConfig) -> str:
    event = campaign.event_name or "Agentic AI Build Week"
    if llm_configured():
        try:
            out: FollowupOutput = generate(
                prompt=(
                    f"Write a short, non-pushy follow-up to {p.contact_name} "
                    f"({p.contact_role} at {p.company_name}) about sponsoring "
                    f"{event}. Previous angle: {p.conversation_angle or p.business_focus}. "
                    f"This is follow-up #{p.followup_count + 1}."
                ),
                schema=FollowupOutput,
                system="You write polite, brief B2B follow-ups. Never guilt-trip.",
            )
            if out.message and out.message.strip():
                return out.message.strip()[:1300 - 1]
        except Exception:
            pass  # fall through to deterministic template

    return (
        f"Hi {p.contact_name.split()[0]} — just floating this back to the top of "
        f"your inbox. We're finalizing sponsor slots for {event} (300+ AI builders, "
        f"Nov 10–14) and {p.company_name} keeps coming up as a natural fit. If the "
        f"timing's off, happy to circle back closer to the event — just say the word."
    )[:1300 - 1]
