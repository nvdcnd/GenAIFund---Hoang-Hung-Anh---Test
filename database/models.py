"""SQLAlchemy models + the strict CRM state machine."""
from __future__ import annotations

import enum
from datetime import datetime, timezone

from sqlalchemy import (
    Boolean,
    DateTime,
    Enum as SAEnum,
    ForeignKey,
    Integer,
    JSON,
    String,
    Text,
    UniqueConstraint,
    create_engine,
)
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, relationship

from config import DATABASE_URL


def utcnow() -> datetime:
    return datetime.now(timezone.utc)


class Base(DeclarativeBase):
    pass


# ────────────────────────────── Enums ──────────────────────────────────────
class PriorityScore(str, enum.Enum):
    HIGH = "HIGH"
    MED = "MED"
    LOW = "LOW"


class ConnectionDegree(str, enum.Enum):
    FIRST = "1ST"
    SECOND_THIRD = "2ND_3RD"


class Sender(str, enum.Enum):
    SYSTEM = "SYSTEM"
    PROSPECT = "PROSPECT"
    HUMAN_AGENT = "HUMAN_AGENT"


class Status(str, enum.Enum):
    RESEARCHED = "RESEARCHED"
    PENDING_REVIEW = "PENDING_REVIEW"
    APPROVED = "APPROVED"
    REJECTED = "REJECTED"
    OUTREACH_SENT = "OUTREACH_SENT"
    FOLLOWING_UP = "FOLLOWING_UP"
    REPLIED = "REPLIED"
    OPT_OUT = "OPT_OUT"
    INTERESTED = "INTERESTED"
    MEETING_PROPOSED = "MEETING_PROPOSED"
    MEETING_CONFIRMED = "MEETING_CONFIRMED"


# ─────────────────── Strict state machine transitions ─────────────────────
ALLOWED_TRANSITIONS: dict[Status, set[Status]] = {
    Status.RESEARCHED: {Status.PENDING_REVIEW, Status.REJECTED},
    Status.PENDING_REVIEW: {Status.APPROVED, Status.REJECTED, Status.RESEARCHED},
    Status.APPROVED: {Status.OUTREACH_SENT, Status.PENDING_REVIEW},
    Status.OUTREACH_SENT: {Status.FOLLOWING_UP, Status.REPLIED, Status.OPT_OUT},
    Status.FOLLOWING_UP: {Status.REPLIED, Status.OPT_OUT},
    Status.REPLIED: {
        Status.OPT_OUT,
        Status.INTERESTED,
        Status.MEETING_PROPOSED,
        Status.OUTREACH_SENT,   # classifier no-op / nothing to stop
        Status.FOLLOWING_UP,
    },
    Status.INTERESTED: {Status.MEETING_PROPOSED, Status.OPT_OUT, Status.REPLIED},
    Status.MEETING_PROPOSED: {Status.MEETING_CONFIRMED, Status.OPT_OUT, Status.REPLIED},
    Status.MEETING_CONFIRMED: {Status.OPT_OUT, Status.REPLIED},
    Status.OPT_OUT: set(),
    Status.REJECTED: set(),
}


class InvalidTransition(Exception):
    pass


def validate_transition(current: Status, target: Status) -> None:
    if target == current:
        return
    if target not in ALLOWED_TRANSITIONS.get(current, set()):
        raise InvalidTransition(
            f"Illegal CRM transition {current.value} -> {target.value}. "
            f"Allowed: {sorted(s.value for s in ALLOWED_TRANSITIONS.get(current, set()))}"
        )


# ────────────────────────────── Models ────────────────────────────────────
class CampaignConfig(Base):
    __tablename__ = "campaigns"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    event_name: Mapped[str] = mapped_column(String(200), default="Agentic AI Build Week")
    brief_text: Mapped[str] = mapped_column(Text, default="")
    target_roles: Mapped[str] = mapped_column(
        String(300), default="Head of AI, VP Engineering, Tech Partnerships"
    )
    target_geo: Mapped[str] = mapped_column(String(200), default="Singapore / Southeast Asia")
    max_followups: Mapped[int] = mapped_column(Integer, default=2)
    delay_days: Mapped[int] = mapped_column(Integer, default=3)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)


class Prospect(Base):
    __tablename__ = "prospects"
    __table_args__ = (UniqueConstraint("company_linkedin", "contact_name", name="uq_prospect"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    # company
    company_name: Mapped[str] = mapped_column(String(200))
    company_website: Mapped[str] = mapped_column(String(300), default="")
    company_linkedin: Mapped[str] = mapped_column(String(300), default="")
    business_focus: Mapped[str] = mapped_column(Text, default="")
    # contact
    contact_name: Mapped[str] = mapped_column(String(200))
    contact_role: Mapped[str] = mapped_column(String(200), default="")
    contact_location: Mapped[str] = mapped_column(String(200), default="")
    contact_email: Mapped[str] = mapped_column(String(200), default="")
    contact_linkedin: Mapped[str] = mapped_column(String(300), default="")
    # research / personalization
    relevance_reasoning: Mapped[str] = mapped_column(Text, default="")
    conversation_angle: Mapped[str] = mapped_column(Text, default="")
    priority_score: Mapped[PriorityScore] = mapped_column(
        SAEnum(PriorityScore, values_callable=lambda e: [i.value for i in e]),
        default=PriorityScore.MED,
    )
    connection_degree: Mapped[ConnectionDegree] = mapped_column(
        SAEnum(ConnectionDegree, values_callable=lambda e: [i.value for i in e]),
        default=ConnectionDegree.SECOND_THIRD,
    )
    sources: Mapped[list] = mapped_column(JSON, default=list)
    flagged_uncertainties: Mapped[str] = mapped_column(Text, default="")
    draft_message: Mapped[str] = mapped_column(Text, default="")
    # pipeline state
    status: Mapped[Status] = mapped_column(
        SAEnum(Status, values_callable=lambda e: [i.value for i in e]),
        default=Status.RESEARCHED,
    )
    needs_human_intervention: Mapped[bool] = mapped_column(Boolean, default=False)
    followup_count: Mapped[int] = mapped_column(Integer, default=0)
    last_activity_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow, onupdate=utcnow)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)

    messages: Mapped[list["MessagesHistory"]] = relationship(
        back_populates="prospect",
        cascade="all, delete-orphan",
        order_by="MessagesHistory.timestamp",
    )

    def set_status(self, target: Status) -> None:
        """Transition with strict state-machine validation."""
        current = self.status if isinstance(self.status, Status) else Status(self.status)
        validate_transition(current, target)
        self.status = target


class MessagesHistory(Base):
    __tablename__ = "messages_history"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    prospect_id: Mapped[int] = mapped_column(ForeignKey("prospects.id"), index=True)
    sender: Mapped[Sender] = mapped_column(
        SAEnum(Sender, values_callable=lambda e: [i.value for i in e])
    )
    content: Mapped[str] = mapped_column(Text)
    timestamp: Mapped[datetime] = mapped_column(DateTime, default=utcnow)
    intent_detected: Mapped[str | None] = mapped_column(String(60), nullable=True)
    is_automated: Mapped[bool] = mapped_column(Boolean, default=False)

    prospect: Mapped[Prospect] = relationship(back_populates="messages")


class AuditEvent(Base):
    """Append-only audit trail (e.g. webhook receipts, manual takeovers)."""

    __tablename__ = "audit_events"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    prospect_id: Mapped[int | None] = mapped_column(
        ForeignKey("prospects.id"), nullable=True, index=True
    )
    event: Mapped[str] = mapped_column(String(100))
    detail: Mapped[str] = mapped_column(Text, default="")
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)


_engine = None


def get_engine():
    """Engine created lazily so imports never touch disk too early."""
    global _engine
    if _engine is None:
        _engine = create_engine(DATABASE_URL, connect_args={"check_same_thread": False})
        Base.metadata.create_all(_engine)
    return _engine
