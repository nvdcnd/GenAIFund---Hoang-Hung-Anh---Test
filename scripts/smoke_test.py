"""End-to-end smoke test: research -> review -> approve -> outreach ->
reply -> classify -> schedule link -> webhook confirm. Run from project root:
    .venv/Scripts/python.exe scripts/smoke_test.py
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from database import db_session
from database.models import Status
from agents import research_agent, enrichment_agent, intent_agent, followup_agent
from drivers.factory import get_driver
from utils.webhook_handler import process_booking

# Self-reset: wipe all rows so the test is repeatable even while the Streamlit
# server keeps the SQLite file open (row-level reset avoids file-lock issues).
from sqlalchemy import text
with db_session.session_scope() as s:
    for tbl in ("audit_events", "messages_history", "prospects", "campaigns"):
        s.execute(text(f"DELETE FROM {tbl}"))
print("(reset demo data)\n")


def expect(cond, label):
    print(f"  {'PASS' if cond else 'FAIL'}: {label}")
    assert cond, label


print("== 1. Research run (mock fixtures) ==")
with db_session.session_scope() as s:
    camp = db_session.get_or_create_campaign(s)
    camp.brief_text = "AI infrastructure companies in SEA with developer audiences."
    found = research_agent.run_research(s, camp)
    expect(len(found) >= 8, f"research found {len(found)} prospects")
    expect(all(p.status == Status.PENDING_REVIEW for p in found), "all PENDING_REVIEW")

print("== 2. Enrichment + approval gate ==")
with db_session.session_scope() as s:
    p = db_session.list_prospects(s)[0]
    enrichment_agent.enrich(s, p.id)
    expect(len(p.draft_message) > 0, "draft generated")
    p.set_status(Status.APPROVED)
    pid, email = p.id, p.contact_email

print("== 3. Outreach send ==")
drv = get_driver()
with db_session.session_scope() as s:
    p = db_session.get_prospect(s, pid)
    ok = followup_agent.send_outreach(s, p, db_session.get_or_create_campaign(s), drv)
    expect(ok and p.status == Status.OUTREACH_SENT, f"status={p.status.value}")

print("== 4. Prospect reply -> STOP-ON-REPLY + classify (interested) ==")
msg_email, msg_name = email, ""
with db_session.session_scope() as s:
    p = db_session.get_prospect(s, pid)
    msg_name = p.contact_name
drv.queue_inbound(msg_email, msg_name, "Sounds interesting — how do we set up a call?")
with db_session.session_scope() as s:
    n = intent_agent.poll_replies(s, drv)
    expect(n == 1, "processed 1 inbound reply")
    p = db_session.get_prospect(s, pid)
    expect(p.status == Status.MEETING_PROPOSED,
           f"reply w/ interest => MEETING_PROPOSED (got {p.status.value})")

print("== 5. Follow-up engine must NOT touch replied prospect ==")
with db_session.session_scope() as s:
    camp = db_session.get_or_create_campaign(s)
    camp.delay_days = 0  # make everything 'due'
    sent = followup_agent.run_followups(s, camp, drv)
    expect(sent == 0, "zero follow-ups sent to non-follow-up states")

print("== 6. Cal.com webhook confirms meeting ==")
res = process_booking({"payload": {"email": msg_email, "name": msg_name}})
expect(res.get("status") == "MEETING_CONFIRMED", f"webhook result={res}")
with db_session.session_scope() as s:
    p = db_session.get_prospect(s, pid)
    expect(p.status == Status.MEETING_CONFIRMED, f"final status={p.status.value}")

print("== 7. Decline path on a second prospect ==")
with db_session.session_scope() as s:
    q = [p for p in db_session.list_prospects(s) if p.id != pid
         and p.status == Status.PENDING_REVIEW][0]
    q.set_status(Status.APPROVED)
    followup_agent.send_outreach(s, q, db_session.get_or_create_campaign(s), drv)
    qid, qemail, qname = q.id, q.contact_email, q.contact_name
drv.queue_inbound(qemail, qname, "Not interested this quarter, please stop contacting.")
with db_session.session_scope() as s:
    intent_agent.poll_replies(s, drv)
    q = db_session.get_prospect(s, qid)
    expect(q.status == Status.OPT_OUT, f"decline => OPT_OUT (got {q.status.value})")

print("\nALL SMOKE TESTS PASSED (OK)")
