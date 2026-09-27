"""Streamlit AppTest coverage: drives the REAL app.py UI.

Closes the last untested layer — the Streamlit wiring itself:
* all four tabs render (and Tab 4's audit grid survives mixed int/'—' rows),
* the Tab 2 approve button really sends outreach (-> OUTREACH_SENT + toast),
* the Tab 4 / Tab 3 flash pattern (session_state -> pop after st.rerun)
  survives the rerun and displays the real result.

AppTest notes that shape this file:
* st.tabs is purely visual here — ONE at.run() renders every tab's widgets,
  so there is no tab-switching step to test.
* st.selectbox value is the selection INDEX; the app's list_prospects()
  order is deterministic, so the index maps to a prospect id via the DB.
* st.cache_resource keeps the app's mock driver private to the app; tests
  therefore only assert observable DB state + rendered widgets, and drive
  reply simulations through the app's own buttons.
"""
from pathlib import Path

import pytest
from streamlit.testing.v1 import AppTest

APP = str(Path(__file__).resolve().parent.parent / "app.py")


@pytest.fixture()
def at():
    return AppTest.from_file(APP, default_timeout=30)


def _no_exception(at: AppTest):
    assert not at.exception, f"app raised: {[e.value for e in at.exception]}"


def _button(at: AppTest, needle: str):
    matches = [b for b in at.button if needle in (b.label or "")]
    assert matches, f"button containing {needle!r} not found"
    return matches[0]


# ───────────────────────────── render smoke ────────────────────────────────
def test_all_four_tabs_render(at):
    at.run()
    _no_exception(at)
    assert len(at.tabs) == 4


def test_tab4_renders_with_mixed_audit_rows(at):
    """Regression: pyarrow crashed the whole server when the audit grid mixed
    integer prospect ids with the '—' fallback (research_run has no id)."""
    at.run()
    _no_exception(at)
    # Tab 4 content (buttons + audit dataframe) is in the tree without switching.
    assert _button(at, "Simulate Cal.com webhook")
    assert len(at.dataframe) >= 1, "audit log dataframe must render"


# ───────────────────────── approve flow (Tab 2) ────────────────────────────
def test_approve_button_sends_outreach(at, session_factory):
    from database import db_session
    from database.models import Status

    at.run()
    _no_exception(at)
    with session_factory() as s:
        before = sum(1 for p in db_session.list_prospects(s)
                     if p.status == Status.OUTREACH_SENT)

    _button(at, "Approve").click()
    at.run()
    _no_exception(at)

    with session_factory() as s:
        sent = [p for p in db_session.list_prospects(s)
                if p.status == Status.OUTREACH_SENT]
    assert len(sent) == before + 1, "approve must move exactly one prospect to OUTREACH_SENT"
    assert sent[0].draft_message, "sent prospect carries a real draft"
    assert any("OUTREACH_SENT" in (v.value or "") for v in at.success), (
        "approval toast must be visible in the same run (no flash needed here)"
    )


# ───────────────────── Tab 4 flash survives rerun ──────────────────────────
def test_tab4_flash_survives_rerun(at, session_factory):
    from database import db_session
    from database.models import Status

    # Pick a still-PENDING prospect and move it into a reply-eligible state
    # (APPROVED -> OUTREACH_SENT is legal without a send; the send path is
    # covered by the approve test above).
    with session_factory() as s:
        prospects = db_session.list_prospects(s)
        target = next(p for p in prospects if p.status == Status.PENDING_REVIEW)
        target.set_status(Status.APPROVED)
        target.set_status(Status.OUTREACH_SENT)
        pid = target.id
        index = prospects.index(next(p for p in prospects if p.id == pid))

    at.run()
    _no_exception(at)

    sel = [x for x in at.selectbox if x.key == "sim_target"][0]
    sel.set_value(index).run()
    _no_exception(at)

    _button(at, "opt-out").click()
    at.run()  # this run contains the button handler's st.rerun()
    _no_exception(at)

    flash = [v.value for v in at.success if "intent engine" in (v.value or "")]
    assert flash, "flash must survive the rerun and render on the fresh run"
    assert f"#{pid}" in flash[0] and "OPT_OUT" in flash[0]

    with session_factory() as s:
        assert db_session.get_prospect(s, pid).status == Status.OPT_OUT


# ───────────────────── Tab 3 poll flash survives rerun ─────────────────────
def test_tab3_poll_flash_survives_rerun(at):
    """With an empty driver inbox the poll flash must still render '0 new
    reply(ies)' after its st.rerun() — the exact pattern that used to wipe
    the message. Count>1 semantics are covered in test_intent_branches."""
    at.run()
    _no_exception(at)

    _button(at, "Check replies").click()
    at.run()
    _no_exception(at)

    flash = [v.value for v in at.success if "Polled inbound" in (v.value or "")]
    assert flash, "poll flash must survive the rerun"
    assert "0 new reply" in flash[0]
