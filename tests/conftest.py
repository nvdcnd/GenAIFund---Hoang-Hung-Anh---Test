"""Test isolation: never touch the real demo DB at data/outreach.db.

config.py resolves DATABASE_URL at import time, so we must set DATABASE_URL
*before* any project module is imported. Tests therefore import nothing from
the project at module top level — they do it inside fixtures/tests, after the
env var is set here.
"""
import os
import tempfile

# Must run before any `database.*` / `config.*` import.
_TMP_DB = os.path.join(tempfile.mkdtemp(prefix="outreach-test-"), "test.db")
os.environ["DATABASE_URL"] = f"sqlite:///{_TMP_DB}"
os.environ.pop("OPENAI_API_KEY", None)  # force MockLLM regardless of developer env
os.environ["WEBHOOK_SECRET"] = "test-webhook-secret"  # enable HTTP-layer secret check

import pytest  # noqa: E402

from database.models import Prospect as _Prospect  # noqa: E402
from drivers.mock_driver import MockLinkedInDriver  # noqa: E402


@pytest.fixture()
def driver():
    """Fresh mock driver per test — in-memory inbox and sent log are private."""
    return MockLinkedInDriver()


@pytest.fixture()
def session_factory():
    """Yield db_session.session_scope bound to the isolated test DB."""
    from database import db_session
    return db_session.session_scope


@pytest.fixture(scope="session", autouse=True)
def seeded_db():
    """Seed the isolated DB once: real research pipeline + extra synthetic
    PENDING rows so the suite's combined fixture demand never exhausts stock
    (driver fixtures alone yield exactly 8 prospects; the suites consume 9)."""
    from agents import research_agent
    from database import db_session
    from database.models import ConnectionDegree, PriorityScore, Status

    with db_session.session_scope() as s:
        camp = db_session.get_or_create_campaign(s)
        research_agent.run_research(s, camp)
        for i in range(6):
            s.add(_Prospect(
                company_name=f"SynthCorp {i}",
                company_linkedin=f"https://linkedin.com/company/synthcorp-{i}",
                contact_name=f"Syn Contact {i}",
                contact_email=f"syn{i}@synthcorp.example",
                connection_degree=ConnectionDegree.SECOND_THIRD,
                priority_score=PriorityScore.MED,
                draft_message=f"Hi Syn — quick note {i}.",
                status=Status.PENDING_REVIEW,
            ))
        assert s.query(_Prospect).filter(
            _Prospect.status == Status.PENDING_REVIEW).count() >= 12


@pytest.fixture()
def sent_prospect(session_factory, driver):
    """One prospect approved + enriched, sent through `send_outreach`.

    Exercises the real pipeline and returns (prospect_id, email, name).
    """
    from agents import enrichment_agent, followup_agent
    from database import db_session
    from database.models import Status

    with session_factory() as s:
        p = s.query(_Prospect).filter(
            _Prospect.status == Status.PENDING_REVIEW).first()
        assert p is not None, "no PENDING_REVIEW prospect left — seeding exhausted"
        enrichment_agent.enrich(s, p.id)
        p.set_status(Status.APPROVED)
        pid, email, name = p.id, p.contact_email, p.contact_name

    with session_factory() as s:
        p = db_session.get_prospect(s, pid)
        followup_agent.send_outreach(
            s, p, db_session.get_or_create_campaign(s), driver)
    return pid, email, name
