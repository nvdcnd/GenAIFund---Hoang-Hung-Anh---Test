"""Enrichment & Personalization Engine — Module 2.

Produces degree-aware, personalized outreach:
* 1st degree       -> detailed DM (<= 1300 chars, LinkedIn DM cap)
* 2nd/3rd degree   -> connection note (<= 300 chars, LinkedIn invite cap)

Also attaches sources used, conversation angle, and explicit uncertainty
flags so a human reviewer can judge data trust in one glance.
"""
from __future__ import annotations

from sqlalchemy.orm import Session

from agents.llm_client import DraftOutput, generate
from database import db_session
from database.models import CampaignConfig, ConnectionDegree, Prospect, Sender, Status
from config import llm_configured


def build_draft(p: Prospect, campaign: CampaignConfig) -> str:
    """Degree-aware personalized outreach text for a prospect."""
    event = campaign.event_name or "Agentic AI Build Week"
    hook = (p.conversation_angle or p.business_focus or "").strip()
    is_first = p.connection_degree == ConnectionDegree.FIRST

    base = (
        f"Hi {p.contact_name.split()[0]} — I'm reaching out from {event} "
        f"(Nov 10–14, 2026; 300+ AI builders across SEA). Your work on "
        f"{p.business_focus} stood out — exactly the audience we're bringing together."
    )
    if is_first:
        base += (
            f" We're inviting a small group of AI-forward teams to sponsor; given "
            f"{p.company_name}'s focus, I think there's a natural fit. Open to a "
            f"quick look at the sponsorship options?"
        )
    else:
        base += (
            f" Would love to connect — we're lining up sponsors for {event} and "
            f"{p.company_name} looks like a strong match."
        )
    base = base[: (1300 if is_first else 300) - 1]

    if llm_configured():
        try:
            out: DraftOutput = generate(
                prompt=(
                    f"Write a {'' if is_first else 'connection request (<=300 chars) '}"
                    f"outreach message to {p.contact_name}, {p.contact_role} at "
                    f"{p.company_name} ({p.contact_location}). Company focus: "
                    f"{p.business_focus}. Campaign brief: {campaign.brief_text}. "
                    f"Event: {event}. Return JSON with keys connection_note and "
                    f"followup_angle."
                ),
                schema=DraftOutput,
                system="You write concise, warm B2B sponsorship outreach.",
            )
            if out.connection_note and out.connection_note.strip():
                return out.connection_note.strip()[: (1300 if is_first else 300) - 1]
        except Exception:
            pass  # fall back to the deterministic template above

    return base


def enrich(session: Session, prospect_id: int) -> Prospect:
    """(Re)generate draft + angle + flags for one prospect; keeps state unchanged."""
    campaign = db_session.get_or_create_campaign(session)
    p = db_session.get_prospect(session, prospect_id)
    if p is None:
        raise ValueError(f"Prospect {prospect_id} not found")

    p.draft_message = build_draft(p, campaign)
    p.sources = list(p.sources or []) or [
        p.company_website,
        p.company_linkedin,
        "agents://enrichment/public-web-synthesis",
    ]
    p.flagged_uncertainties = (
        p.flagged_uncertainties
        or "Contact email inferred from public patterns; recent company news not verified."
    )
    session.flush()
    return p
