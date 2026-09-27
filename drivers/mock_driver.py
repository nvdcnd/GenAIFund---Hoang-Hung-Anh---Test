"""Zero-budget mock LinkedIn driver — deterministic simulation sandbox.

* search_prospects: returns 8 curated fixture prospects (research pre-filled).
* send_message: records the send, auto-replies to a fraction of sends so the
  full pipeline (reply -> classify -> book) can be exercised without keys.
* check_replies: returns queued inbound messages (also fed by the dashboard's
  simulate-reply buttons).
"""
from __future__ import annotations

import random
from typing import List

from drivers.linkedin_base import InboundMessage, LinkedInProvider, ScanResult, SendResult
from database.models import ConnectionDegree, PriorityScore, Prospect, Status

# ─────────────────────────── fixture companies ─────────────────────────────
_FIXTURES: List[dict] = [
    dict(company_name="SeaStack AI", company_website="https://seastack.example",
         company_linkedin="https://linkedin.com/company/seastack-ai",
         business_focus="LLM inference platform optimised for Southeast Asian languages",
         contact_name="Priya Raman", contact_role="Head of AI",
         contact_location="Singapore", contact_email="priya@seastack.example",
         contact_linkedin="https://linkedin.com/in/priya-raman",
         connection_degree=ConnectionDegree.SECOND_THIRD, priority_score=PriorityScore.HIGH),
    dict(company_name="KiloCloud", company_website="https://kilocloud.example",
         company_linkedin="https://linkedin.com/company/kilocloud",
         business_focus="Serverless GPU cloud for ML training and batch inference",
         contact_name="Marcus Tan", contact_role="VP Engineering",
         contact_location="Singapore", contact_email="marcus@kilocloud.example",
         contact_linkedin="https://linkedin.com/in/marcus-tan",
         connection_degree=ConnectionDegree.FIRST, priority_score=PriorityScore.HIGH),
    dict(company_name="AtlasVector", company_website="https://atlasvector.example",
         company_linkedin="https://linkedin.com/company/atlasvector",
         business_focus="Managed vector database with hybrid search",
         contact_name="Lina Wijaya", contact_role="Director of Partnerships",
         contact_location="Jakarta", contact_email="lina@atlasvector.example",
         contact_linkedin="https://linkedin.com/in/lina-wijaya",
         connection_degree=ConnectionDegree.SECOND_THIRD, priority_score=PriorityScore.MED),
    dict(company_name="NexusAgents", company_website="https://nexusagents.example",
         company_linkedin="https://linkedin.com/company/nexusagents",
         business_focus="Open-source multi-agent orchestration framework",
         contact_name="Daniel Ong", contact_role="CTO",
         contact_location="Singapore", contact_email="daniel@nexusagents.example",
         contact_linkedin="https://linkedin.com/in/daniel-ong",
         connection_degree=ConnectionDegree.FIRST, priority_score=PriorityScore.HIGH),
    dict(company_name="BetaML Labs", company_website="https://betaml.example",
         company_linkedin="https://linkedin.com/company/betaml-labs",
         business_focus="MLOps tooling for regulated industries",
         contact_name="Sofia Cruz", contact_role="Head of Developer Relations",
         contact_location="Manila", contact_email="sofia@betaml.example",
         contact_linkedin="https://linkedin.com/in/sofia-cruz",
         connection_degree=ConnectionDegree.SECOND_THIRD, priority_score=PriorityScore.MED),
    dict(company_name="QuantifyData", company_website="https://quantifydata.example",
         company_linkedin="https://linkedin.com/company/quantifydata",
         business_focus="Synthetic data generation for LLM fine-tuning",
         contact_name="Ahmed Rahman", contact_role="Tech Partnerships Lead",
         contact_location="Kuala Lumpur", contact_email="ahmed@quantifydata.example",
         contact_linkedin="https://linkedin.com/in/ahmed-rahman",
         connection_degree=ConnectionDegree.SECOND_THIRD, priority_score=PriorityScore.LOW),
    dict(company_name="OrbitRobotics", company_website="https://orbitrobotics.example",
         company_linkedin="https://linkedin.com/company/orbitrobotics",
         business_focus="Warehouse automation robots with vision-language models",
         contact_name="Grace Lim", contact_role="VP Product",
         contact_location="Singapore", contact_email="grace@orbitrobotics.example",
         contact_linkedin="https://linkedin.com/in/grace-lim",
         connection_degree=ConnectionDegree.FIRST, priority_score=PriorityScore.LOW),
    dict(company_name="LinguaForge", company_website="https://linguaforge.example",
         company_linkedin="https://linkedin.com/company/linguaforge",
         business_focus="Real-time speech translation for enterprise CX",
         contact_name="Ravi Chandran", contact_role="Head of Engineering",
         contact_location="Bengaluru", contact_email="ravi@linguaforge.example",
         contact_linkedin="https://linkedin.com/in/ravi-chandran",
         connection_degree=ConnectionDegree.SECOND_THIRD, priority_score=PriorityScore.MED),
]

_REASONING = {
    "HIGH": "Company builds core AI infrastructure targeted at the hackathon's builder "
            "audience; contact owns technical/technical-partnership decisions and is "
            "based in the target geography, so sponsorship ROI is direct and near-term.",
    "MED": "Company is AI-adjacent with a developer audience overlap; contact influences "
           "but does not solely own sponsorship budget, making them a strong secondary target.",
    "LOW": "Partial audience overlap only; contact is product-side with no clear sponsor "
           "mandate — keep in the long-term nurture pool.",
}


class MockLinkedInDriver(LinkedInProvider):
    name = "mock"

    def __init__(self) -> None:
        self.sent_log: List[dict] = []
        self._inbox: List[InboundMessage] = []
        self._rng = random.Random(42)  # deterministic, reproducible demos

    # ── search ───────────────────────────────────────────────────────────
    def search_prospects(self, query: dict) -> List[Prospect]:
        roles = str(query.get("target_roles", "")).lower()
        geo = str(query.get("target_geo", "")).lower()
        out: List[Prospect] = []
        for f in _FIXTURES:
            p = Prospect(
                company_name=f["company_name"],
                company_website=f["company_website"],
                company_linkedin=f["company_linkedin"],
                business_focus=f["business_focus"],
                contact_name=f["contact_name"],
                contact_role=f["contact_role"],
                contact_location=f["contact_location"],
                contact_email=f["contact_email"],
                contact_linkedin=f["contact_linkedin"],
                connection_degree=f["connection_degree"],
                priority_score=f["priority_score"],
                relevance_reasoning=_REASONING[f["priority_score"].value],
                sources=[
                    f["company_website"],
                    f["company_linkedin"],
                    "mock://fixture-dataset/ai-companies-sea-2026",
                ],
                flagged_uncertainties=(
                    "MOCK DATA: fixture record for zero-budget demo; email is a placeholder "
                    "and employment data unverified."
                ),
                status=Status.RESEARCHED,
            )
            # Geo/role affinity nudges the score so research looks data-driven.
            if geo.split("/")[0].strip() and f["contact_location"].lower() in geo:
                p.priority_score = (
                    PriorityScore.HIGH if f["priority_score"] == PriorityScore.HIGH
                    else PriorityScore.MED
                )
            p.status = Status.RESEARCHED
            out.append(p)
        return out

    # ── send ─────────────────────────────────────────────────────────────
    def send_message(self, prospect: Prospect, text: str) -> SendResult:
        self._validate(text)
        self.sent_log.append({
            "prospect_id": prospect.id,
            "to": prospect.contact_name,
            "text": text,
        })
        # ~45% of cold sends get an eventual mock reply so demos show the
        # full reply-handling pipeline deterministically enough.
        if self._rng.random() < 0.45:
            self._queue_reply(prospect)
        return SendResult(ok=True, driver=self.name,
                          external_id=f"mock-{len(self.sent_log)}",
                          note="Simulated send (mock driver)")

    # ── replies ──────────────────────────────────────────────────────────
    def check_replies(self) -> ScanResult:
        items, self._inbox = self._inbox, []
        return ScanResult(ok=True, driver=self.name, items=items)

    def queue_inbound(self, prospect_email: str, prospect_name: str, text: str) -> None:
        """Used by the dashboard's simulation buttons."""
        self._inbox.append(InboundMessage(
            prospect_email=prospect_email, prospect_name=prospect_name, text=text,
        ))

    # ── internal ─────────────────────────────────────────────────────────
    def _queue_reply(self, prospect: Prospect) -> None:
        snippets = [
            "Thanks for reaching out — what does sponsorship involve exactly?",
            "Not the right time this quarter, sorry.",
            "Interesting. Can you share the sponsorship deck and pricing?",
            "We could be interested — how do we set up a quick call?",
        ]
        self._inbox.append(InboundMessage(
            prospect_email=prospect.contact_email,
            prospect_name=prospect.contact_name,
            text=self._rng.choice(snippets),
        ))
