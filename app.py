"""GenAI Fund — Agentic AI LinkedIn Outreach & Booking Automation (HITL Dashboard).

Run:  .venv/Scripts/streamlit.exe run app.py --server.port 8501
Tabs: 1) Campaign Setup  2) Prospect Review & Approval
      3) Conversation Tracker & CRM  4) Recruiter Testing & Simulation Suite
"""
from __future__ import annotations

import datetime as dt

import streamlit as st
from sqlalchemy import text
from sqlalchemy import text

from config import LINKEDIN_DRIVER, LLM_MODEL, llm_configured
from database import db_session
from database.models import AuditEvent, PriorityScore, Sender, Status
from agents import enrichment_agent, followup_agent, intent_agent, research_agent
from drivers.factory import get_driver
from utils.webhook_handler import process_booking

st.set_page_config(
    page_title="GenAI Fund — AI Outreach Automation",
    page_icon="🤝",
    layout="wide",
)

STATUS_EMOJI = {
    Status.RESEARCHED: "🔍", Status.PENDING_REVIEW: "🟡", Status.APPROVED: "✅",
    Status.REJECTED: "🗑️", Status.OUTREACH_SENT: "📤", Status.FOLLOWING_UP: "🔁",
    Status.REPLIED: "💬", Status.OPT_OUT: "🚫", Status.INTERESTED: "🌟",
    Status.MEETING_PROPOSED: "📅", Status.MEETING_CONFIRMED: "🤝",
}
SENDER_ICON = {Sender.SYSTEM: "🤖", Sender.PROSPECT: "👤", Sender.HUMAN_AGENT: "🧑‍💼"}
PRIORITY_EMOJI = {"HIGH": "🔴", "MED": "🟠", "LOW": "🟢"}


@st.cache_resource
def cached_driver(name: str):
    """One driver instance for the app's lifetime (keeps mock inbox alive)."""
    return get_driver(name)


def drv():
    return cached_driver(LINKEDIN_DRIVER)


def fresh_session():
    """Streamlit reruns top-to-bottom; always open a new scoped session."""
    return db_session.session_scope()


# ─────────────────────────────── sidebar ───────────────────────────────────
with st.sidebar:
    st.title("🤝 AI Outreach Console")
    st.caption("GenAI Fund · Agentic AI Build Week")

    st.markdown("**Runtime mode**")
    st.markdown(
        f"- LLM: {'🟢 ' + LLM_MODEL if llm_configured() else '⚪ MockLLM (zero-budget)'}\n"
        f"- LinkedIn driver: **{LINKEDIN_DRIVER}**"
    )

    with st.expander("⚠️ Danger zone"):
        if st.checkbox("I understand this wipes all demo data"):
            if st.button("🗑️ Reset database", type="primary"):
                with fresh_session() as s:
                    for tbl in ("audit_events", "messages_history", "prospects", "campaigns"):
                        s.execute(text(f"DELETE FROM {tbl}"))
                st.cache_resource.clear()
                st.success("Database reset.")


# ─────────────────────────────── tabs ──────────────────────────────────────
tab1, tab2, tab3, tab4 = st.tabs(
    ["⚙️ Campaign Setup", "🎯 Prospect Review & Approval",
     "💬 Conversation Tracker & CRM", "🧪 Recruiter Testing & Simulation"]
)


# ═════════════════════════ TAB 1: CAMPAIGN SETUP ═══════════════════════════
with tab1:
    st.header("⚙️ Campaign Setup")
    with fresh_session() as s:
        camp = db_session.get_or_create_campaign(s)

        c1, c2 = st.columns(2)
        with c1:
            event_name = st.text_input("Event name", value=camp.event_name)
            target_roles = st.text_input(
                "Target roles (ICP personas)", value=camp.target_roles)
            target_geo = st.text_input("Target geography", value=camp.target_geo)
        with c2:
            max_followups = st.number_input(
                "Max follow-ups per prospect", 0, 5,
                value=min(int(camp.max_followups), 5))
            delay_days = st.number_input(
                "Days between touches", 1, 30, value=max(1, int(camp.delay_days)))
        brief_text = st.text_area(
            "Campaign brief (ICP, event context, what sponsors get)",
            value=camp.brief_text,
            placeholder="e.g. Sponsoring Agentic AI Build Week puts your brand in front of "
                        "300+ AI engineers and startup builders across SEA…",
            height=140,
        )

        if st.button("💾 Save campaign", type="primary"):
            camp.event_name, camp.target_roles = event_name, target_roles
            camp.target_geo, camp.brief_text = target_geo, brief_text
            camp.max_followups, camp.delay_days = int(max_followups), int(delay_days)
            db_session.log_audit(s, event="campaign_saved")
            st.success("Campaign saved.")

    st.divider()
    st.subheader("🔎 Run the Research Agent")
    st.caption("Discovers companies + personas matching the ICP, dedupes, and queues "
               "them for human review (Tab 2). Mock driver ships 8 curated SEA AI "
               "fixtures so the demo runs free.")
    if st.button("🚀 Run research now", type="primary"):
        with fresh_session() as s:
            camp = db_session.get_or_create_campaign(s)
            camp.brief_text = brief_text or camp.brief_text
            found = research_agent.run_research(s, camp, driver=drv())
        st.success(f"Research complete — {len(found)} new prospect(s) moved to review.")


# ══════════════════════ TAB 2: REVIEW & APPROVAL ═══════════════════════════
with tab2:
    st.header("🎯 Prospect Review & Approval")

    with fresh_session() as s:
        queue = db_session.list_prospects(s, statuses=[Status.PENDING_REVIEW])
        if not queue:
            st.info("Review queue is empty — run research in Tab 1 first.")
        else:
            labels = [f"{PRIORITY_EMOJI[p.priority_score.value]} "
                      f"{p.company_name} — {p.contact_name} ({p.contact_role})"
                      for p in queue]
            choice = st.selectbox("Prospect in review queue", range(len(queue)),
                                  format_func=lambda i: labels[i])
            p = queue[choice]

            left, right = st.columns([3, 2])
            with left:
                st.markdown(f"#### {p.company_name}")
                st.markdown(
                    f"**Business focus:** {p.business_focus}  \n"
                    f"**Contact:** {p.contact_name} · {p.contact_role} · "
                    f"{p.contact_location}  \n"
                    f"**LinkedIn:** {p.contact_linkedin or '—'} · "
                    f"**Email:** {p.contact_email or '—'}  \n"
                    f"**Degree:** {p.connection_degree.value}"
                    f"{' (DM allowed)' if p.connection_degree.value == '1ST' else ' (connection note ≤300 chars)'}"
                )
                priority = st.selectbox(
                    "Priority score", ["HIGH", "MED", "LOW"],
                    index=["HIGH", "MED", "LOW"].index(p.priority_score.value))
                st.markdown("**Why this company / person?**")
                st.write(p.relevance_reasoning)
                st.markdown("**Conversation angle / hook**")
                angle = st.text_area("angle", value=p.conversation_angle, height=70,
                                     label_visibility="collapsed")
            with right:
                st.markdown("**📎 Sources used**")
                for src in p.sources or []:
                    st.markdown(f"- {src}")
                st.markdown("**⚠️ Flagged uncertainties**")
                st.warning(p.flagged_uncertainties or "None", icon="⚠️")

            st.markdown("#### ✍️ Outreach draft (editable)")
            draft = st.text_area(
                "draft",
                value=p.draft_message, height=170, label_visibility="collapsed",
                help=f"{len(p.draft_message)} chars"
                     f"{' — ⚠️ over the 300-char connection-note cap' if len(p.draft_message) > 300 and p.connection_degree.value != '1ST' else ''}",
            )

            b1, b2, b3, b4 = st.columns(4)
            pid = p.id
            if b1.button("✅ Approve & Initiate Outreach", type="primary"):
                with fresh_session() as s2:
                    p2 = db_session.get_prospect(s2, pid)
                    p2.draft_message, p2.conversation_angle = draft, angle
                    p2.priority_score = p2.priority_score.__class__(priority)
                    p2.set_status(Status.APPROVED)
                    try:
                        followup_agent.send_outreach(
                            s2, p2, db_session.get_or_create_campaign(s2), drv())
                        st.success(f"Outreach sent to {p2.contact_name} — status "
                                   f"OUTREACH_SENT. Check Tab 3.")
                    except Exception as e:
                        st.error(f"Send failed: {e}")
            if b2.button("💾 Save Draft"):
                with fresh_session() as s2:
                    p2 = db_session.get_prospect(s2, pid)
                    p2.draft_message, p2.conversation_angle = draft, angle
                    p2.priority_score = p2.priority_score.__class__(priority)
                    db_session.log_audit(s2, event="draft_saved", prospect_id=pid)
                st.success("Draft saved.")
            if b3.button("🗑️ Reject Prospect"):
                with fresh_session() as s2:
                    p2 = db_session.get_prospect(s2, pid)
                    p2.draft_message = draft
                    p2.set_status(Status.REJECTED)
                    db_session.log_audit(s2, event="prospect_rejected", prospect_id=pid)
                st.rerun()
            if b4.button("🔄 Regenerate draft"):
                with fresh_session() as s2:
                    p2 = db_session.get_prospect(s2, pid)
                    p2.conversation_angle = angle
                    enrichment_agent.enrich(s2, pid)
                st.rerun()


# ═══════════════════ TAB 3: CONVERSATIONS & CRM ════════════════════════════
with tab3:
    st.header("💬 Conversation Tracker & CRM")

    # Same flash pattern as Tab 4: persist poll results across st.rerun().
    if st.session_state.get("tab3_flash"):
        st.success(st.session_state.pop("tab3_flash"))

    with fresh_session() as s:
        prospects = db_session.list_prospects(s)
        if not prospects:
            st.info("No prospects yet.")
        else:
            rows = [{
                "ID": p.id, "Company": p.company_name, "Contact": p.contact_name,
                "Role": p.contact_role, "Priority": p.priority_score.value,
                "Status": f"{STATUS_EMOJI[p.status]} {p.status.value}",
                "Follow-ups": f"{p.followup_count}",
                "Needs human": "🚨" if p.needs_human_intervention else "",
                "Last activity": (p.last_activity_at or p.created_at).strftime("%Y-%m-%d %H:%M"),
            } for p in prospects]
            st.dataframe(rows, use_container_width=True, hide_index=True)

            ids = [f"#{p.id} · {p.company_name} · {p.contact_name} · "
                   f"{STATUS_EMOJI[p.status]} {p.status.value}" for p in prospects]
            sel = st.selectbox("Open conversation", range(len(prospects)),
                               format_func=lambda i: ids[i])
            p = prospects[sel]
            pid = p.id

            st.markdown("#### 🧵 Message log")
            for m in db_session.get_messages(s, pid):
                who = SENDER_ICON.get(m.sender, "•")
                badge = f" · intent: `{m.intent_detected}`" if m.intent_detected else ""
                auto = " *(automated)*" if m.is_automated else ""
                with st.chat_message("assistant" if m.sender != Sender.PROSPECT else "user"):
                    st.markdown(
                        f"**{who} {m.sender.value}{auto}**{badge}  \n{m.content}")

            st.divider()
            st.markdown("#### 🧑‍💼 Manual takeover")
            st.caption("Pauses all automation for this prospect (follow-ups skip it) "
                       "and logs your message as HUMAN_AGENT.")
            human_msg = st.text_area("Your message", key="takeover", height=90)
            col_a, col_b, col_c = st.columns(3)
            if col_a.button("📨 Send as human agent"):
                if human_msg.strip():
                    with fresh_session() as s2:
                        p2 = db_session.get_prospect(s2, pid)
                        p2.needs_human_intervention = True  # pause AI
                        db_session.log_message(s2, pid, Sender.HUMAN_AGENT,
                                               human_msg, intent="MANUAL")
                        db_session.log_audit(s2, event="manual_takeover",
                                             prospect_id=pid)
                    st.success("Sent; AI paused for this prospect.")
                else:
                    st.warning("Write a message first.")
            if col_b.button("▶️ Resume AI automation"):
                with fresh_session() as s2:
                    p2 = db_session.get_prospect(s2, pid)
                    p2.needs_human_intervention = False
                    db_session.log_audit(s2, event="automation_resumed",
                                         prospect_id=pid)
                st.success("Automation resumed.")
            if col_c.button("📬 Check replies now"):
                with fresh_session() as s2:
                    n = intent_agent.poll_replies(s2, drv())
                st.session_state["tab3_flash"] = (
                    f"Polled inbound — {n} new reply(ies) processed.")
                st.rerun()


# ═══════════════ TAB 4: RECRUITER TESTING & SIMULATION ═════════════════════
with tab4:
    st.header("🧪 Recruiter Testing & Simulation Suite")
    st.caption("One-click edge cases so a recruiter can evaluate every branch of the "
               "reply engine, the STOP-ON-REPLY rule, and meeting conversion — "
               "without any paid APIs.")

    # Flash message persisted across st.rerun() — a bare st.success() right before
    # a rerun is wiped before anyone can read it, so we show it after the rerun.
    if st.session_state.get("tab4_flash"):
        st.success(st.session_state.pop("tab4_flash"))

    with fresh_session() as s:
        prospects = db_session.list_prospects(s)
        if not prospects:
            st.info("Run research + outreach first (Tabs 1–2).")
        else:
            ids = [f"#{p.id} · {p.company_name} · {p.contact_name} · "
                   f"{STATUS_EMOJI[p.status]} {p.status.value}" for p in prospects]
            sel = st.selectbox("Simulation target", range(len(prospects)),
                               format_func=lambda i: ids[i], key="sim_target")
            target = prospects[sel]
            t_email, t_name, t_id = target.contact_email, target.contact_name, target.id

            st.markdown("##### 👤 Simulate prospect reply (routes through the intent agent)")
            simulations = {
                "❌ Rejection / opt-out":
                    "Thanks, but we're not interested this quarter. Please stop contacting us.",
                "📄 Ask sponsorship deck / info":
                    "Interesting — can you share the sponsorship deck and pricing details?",
                "🧠 Complex question / price negotiation":
                    "What ROI did prior sponsors see, and can you do better on the SGD 25k "
                    "Titanium tier? Our procurement cycle closes in Q3 — who owns budget "
                    "sign-off on your side?",
                "🌟 Expressed interest / request booking":
                    "We like this a lot — how do we set up a quick call this week?",
            }
            for label, reply_text in simulations.items():
                if st.button(label, use_container_width=True):
                    driver = drv()
                    driver.queue_inbound(t_email, t_name, reply_text)
                    with fresh_session() as s2:
                        n = intent_agent.poll_replies(s2, driver)
                        t2 = db_session.get_prospect(s2, t_id)
                        result_line = f"#{t_id} → {t2.status.value}"
                    st.session_state["tab4_flash"] = (
                        f"Reply processed through intent engine — {result_line}. "
                        f"Open Tab 3 to see classification + message log.")
                    st.rerun()

            st.divider()
            st.markdown("##### 📅 Simulate Cal.com webhook (meeting conversion)")
            st.caption("CRITICAL RULE live-proof: MEETING_CONFIRMED is only reachable "
                       "from MEETING_PROPOSED via webhook payload.")
            if st.button("🔔 Simulate Cal.com webhook: meeting booked",
                         use_container_width=True):
                try:
                    res = process_booking({"payload": {"email": t_email, "name": t_name}})
                    st.session_state["tab4_flash"] = (
                        f"Webhook accepted: prospect #{res.get('prospect_id')} → "
                        f"{res.get('status')}")
                    st.rerun()
                except Exception as e:
                    st.error(f"Webhook rejected: {e}")

            st.divider()
            st.markdown("##### 🔁 Automated follow-up cron job")
            camp = db_session.get_or_create_campaign(s)
            st.caption(f"Cadence: every {camp.delay_days} day(s), max "
                       f"{camp.max_followups} follow-up(s). Only OUTREACH_SENT / "
                       f"FOLLOWING_UP prospects are eligible — anyone who replied is "
                       f"structurally excluded (STOP-ON-REPLY).")
            c1, c2 = st.columns(2)
            if c1.button("⏩ Force all active prospects 'due' (demo aid)"):
                with fresh_session() as s2:
                    for p2 in db_session.list_prospects(
                            s2, statuses=[Status.OUTREACH_SENT, Status.FOLLOWING_UP]):
                        p2.last_activity_at = (
                            p2.last_activity_at or dt.datetime.now(dt.timezone.utc)
                        ) - dt.timedelta(days=camp.delay_days + 1)
                    db_session.log_audit(s2, event="demo_force_due")
                st.success("Cadence clock rolled forward for active prospects.")
            if c2.button("⚙️ Trigger follow-up cron pass", type="primary"):
                with fresh_session() as s2:
                    camp2 = db_session.get_or_create_campaign(s2)
                    sent = followup_agent.run_followups(s2, camp2, drv())
                st.success(f"Cron pass complete — {sent} follow-up(s) sent.")

    st.divider()
    st.markdown("##### 🧾 Audit log (latest 25)")
    with fresh_session() as s:
        events = list(s.query(AuditEvent).order_by(AuditEvent.id.desc()).limit(25))
        if events:
            st.dataframe(
                [{"When": e.created_at.strftime("%m-%d %H:%M:%S"), "Event": e.event,
                  # str() keeps the column uniform: mixing ints with the em-dash
                  # fallback crashes pyarrow's type inference and kills the server.
                  "Prospect": str(e.prospect_id) if e.prospect_id else "—",
                  "Detail": e.detail} for e in events],
                use_container_width=True, hide_index=True)
        else:
            st.caption("No audit events yet.")
