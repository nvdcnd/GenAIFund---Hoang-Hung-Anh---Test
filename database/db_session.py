"""DB connection & helper functions used across the app."""
from __future__ import annotations

from contextlib import contextmanager
from datetime import datetime, timedelta, timezone
from typing import Iterator, Optional

from sqlalchemy import case, select
from sqlalchemy.orm import Session, sessionmaker

from database.models import (
    AuditEvent,
    CampaignConfig,
    MessagesHistory,
    PriorityScore,
    Prospect,
    Sender,
    Status,
    get_engine,
)

SessionLocal = sessionmaker(bind=get_engine(), expire_on_commit=False)


@contextmanager
def session_scope() -> Iterator[Session]:
    """Transactional scope: commits on success, rolls back on error."""
    s = SessionLocal()
    try:
        yield s
        s.commit()
    except Exception:
        s.rollback()
        raise
    finally:
        s.close()


# ──────────────────────────── campaigns ────────────────────────────────────
def get_or_create_campaign(session: Session) -> CampaignConfig:
    camp = session.scalar(select(CampaignConfig).order_by(CampaignConfig.id.desc()).limit(1))
    if camp is None:
        camp = CampaignConfig()
        session.add(camp)
        session.flush()
    return camp


# ──────────────────────────── prospects ────────────────────────────────────
def list_prospects(session: Session, statuses: Optional[list[Status]] = None) -> list[Prospect]:
    # Enum column stores strings (values_callable), so SQL ORDER BY is alphabetical:
    # plain ASC yields HIGH, LOW, MED and DESC yields MED, LOW, HIGH — both wrong.
    # Rank explicitly: HIGH first, then MED, then LOW (ties broken by id).
    priority_rank = case(
        (Prospect.priority_score == PriorityScore.HIGH, 1),
        (Prospect.priority_score == PriorityScore.MED, 2),
        else_=3,
    )
    stmt = select(Prospect).order_by(priority_rank, Prospect.id)
    if statuses:
        stmt = stmt.where(Prospect.status.in_(statuses))
    return list(session.scalars(stmt))


def get_prospect(session: Session, prospect_id: int) -> Optional[Prospect]:
    return session.get(Prospect, prospect_id)


def find_prospect_by_email_or_name(
    session: Session, email: str = "", name: str = ""
) -> Optional[Prospect]:
    if email:
        p = session.scalar(select(Prospect).where(Prospect.contact_email == email.strip().lower()))
        if p:
            return p
    if name:
        p = session.scalar(select(Prospect).where(Prospect.contact_name == name.strip()))
        if p:
            return p
        # fuzzy fallback: first token of the name
        first = name.strip().split()[0]
        p = session.scalar(select(Prospect).where(Prospect.contact_name.like(f"{first}%")))
        return p
    return None


# ──────────────────────────── messages ─────────────────────────────────────
def log_message(
    session: Session,
    prospect_id: int,
    sender: Sender,
    content: str,
    intent: Optional[str] = None,
    is_automated: bool = False,
) -> MessagesHistory:
    msg = MessagesHistory(
        prospect_id=prospect_id,
        sender=sender,
        content=content.strip(),
        intent_detected=intent,
        is_automated=is_automated,
    )
    prospect = session.get(Prospect, prospect_id)
    if prospect:
        prospect.last_activity_at = datetime.now(timezone.utc)
    session.add(msg)
    session.flush()
    return msg


def get_messages(session: Session, prospect_id: int) -> list[MessagesHistory]:
    return list(
        session.scalars(
            select(MessagesHistory)
            .where(MessagesHistory.prospect_id == prospect_id)
            .order_by(MessagesHistory.timestamp)
        )
    )


# ──────────────────────────── audit ────────────────────────────────────────
def log_audit(session: Session, event: str, prospect_id: Optional[int] = None, detail: str = "") -> None:
    session.add(AuditEvent(prospect_id=prospect_id, event=event, detail=detail))


# ─────────────────────── follow-up due-date helper ─────────────────────────
def is_followup_due(prospect: Prospect, max_followups: int, delay_days: int) -> bool:
    """A prospect is due for a follow-up only when still unreplied and cadence passed."""
    if prospect.status not in (Status.OUTREACH_SENT, Status.FOLLOWING_UP):
        return False
    if prospect.followup_count >= max_followups:
        return False
    last = prospect.last_activity_at
    if last is None:
        return True
    if last.tzinfo is None:
        last = last.replace(tzinfo=timezone.utc)
    return datetime.now(timezone.utc) >= last + timedelta(days=delay_days)
