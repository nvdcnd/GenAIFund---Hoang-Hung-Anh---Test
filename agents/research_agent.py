"""Research Agent — Module 1: find companies + personas matching the ICP.

In mock mode this uses the driver's curated fixture dataset (8 SEA AI
companies). With a configured driver/LLM it becomes the LLM + provider
research pipeline. Output is always persisted prospects in RESEARCHED state,
then transitioned to PENDING_REVIEW for the HITL approval gate.
"""
from __future__ import annotations

from typing import List

from sqlalchemy import select
from sqlalchemy.orm import Session

from database import db_session
from database.models import CampaignConfig, Prospect, Status
from drivers.factory import get_driver
from drivers.linkedin_base import LinkedInProvider


def run_research(session: Session, campaign: CampaignConfig,
                 driver: LinkedInProvider | None = None) -> List[Prospect]:
    """Discover prospects for the campaign, dedupe, persist, queue for review."""
    drv = driver or get_driver()
    found: List[Prospect] = drv.search_prospects({
        "target_roles": campaign.target_roles,
        "target_geo": campaign.target_geo,
        "brief": campaign.brief_text,
        "event_name": campaign.event_name,
    })

    saved: List[Prospect] = []
    for p in found:
        existing = session.scalar(
            select(Prospect).where(
                Prospect.company_linkedin == (p.company_linkedin or ""),
                Prospect.contact_name == p.contact_name,
            )
        )
        if existing is not None:
            continue  # dedupe across repeated research runs

        if not p.draft_message:
            p.draft_message = default_draft(p, campaign)
        session.add(p)
        saved.append(p)

    session.flush()
    # Move fresh finds to the review queue (RESEARCHED -> PENDING_REVIEW).
    for p in saved:
        p.set_status(Status.PENDING_REVIEW)
    session.flush()
    db_session.log_audit(
        session, event="research_run", detail=f"{len(saved)} new prospect(s) discovered"
    )
    return saved


def default_draft(p: Prospect, campaign: CampaignConfig) -> str:
    """Baseline outreach draft (LLM-refined later by the enrichment agent)."""
    from agents.enrichment_agent import build_draft
    return build_draft(p, campaign)
