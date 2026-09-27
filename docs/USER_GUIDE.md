# User Guide — running and demoing the prototype

Audience: a nontechnical evaluator (or the candidate filming the demo video).
Everything below is clickable buttons; no terminal work is required after the
two-command setup. Technical detail lives in `docs/ARCHITECTURE.md`.

---

## 1. Setup (two commands, no API keys)

```bash
py -3.13 -m venv .venv                        # any Python 3.11+ works
.venv\Scripts\pip install -r requirements.txt
```

Start the dashboard:

```bash
.venv\Scripts\streamlit.exe run app.py --server.port 8501
```

Open **http://localhost:8501**. The sidebar confirms the runtime mode:

- **LLM: ⚪ MockLLM (zero-budget)** — deterministic, no key needed
- **LinkedIn driver: mock** — simulated LinkedIn, no account touched

If `data/outreach.db` already exists (it ships with the repo's demo state), the
dashboard opens with 8 prospects ready to go. To start from scratch, expand
**⚠️ Danger zone** in the sidebar, tick the confirmation, and click
**🗑️ Reset database**, then press **🚀 Run research now** in Tab 1.

---

## 2. The four tabs (what each one is for)

| Tab | Purpose | Who uses it |
|---|---|---|
| ⚙️ **Campaign Setup** | Edit the event brief, target roles/geo, follow-up cap and cadence; launch the research agent | Organizer, once per campaign |
| 🎯 **Prospect Review & Approval** | Read the research dossier per prospect, edit the draft, approve / reject / regenerate | Human reviewer — **the approval gate** |
| 💬 **Conversation Tracker & CRM** | Full message log with intent tags, live statuses, manual takeover | Human reviewer, day-to-day |
| 🧪 **Recruiter Testing & Simulation** | One-click reply scenarios, Cal.com webhook simulator, cron trigger, audit log | Evaluators & demo |

Nothing is ever sent to anyone without a human clicking
**✅ Approve & Initiate Outreach** — that is the core HITL guarantee.

---

## 3. Everyday workflow (the 7 steps)

### Step 1 — Configure and research (Tab 1)
Review the pre-filled brief (event, audience, ICP). Adjust roles/geo if needed →
**💾 Save campaign** → **🚀 Run research now**. The research agent produces
prospects with priority, reasoning, and sources; they land in the review queue.

### Step 2 — Review and approve (Tab 2)
Pick a prospect from the dropdown. The dossier shows: business focus, contact
role/location, LinkedIn + email, connection degree, priority, **why this
company**, **conversation angle**, sources, and flagged uncertainties.
Edit the draft if you wish (the char counter warns above the 300/1300 caps) →
**✅ Approve & Initiate Outreach**. Status → `OUTREACH_SENT`; the audit trail
logs the send. **Save Draft** keeps edits without sending; **Reject Prospect**
permanently benches them; **🔄 Regenerate draft** rewrites from the angle.

### Step 3 — Watch the cadence or force it (Tab 4)
In real life a scheduler triggers follow-ups every N days. In the demo:
**⏩ Force all active prospects 'due'** then **⚙️ Trigger follow-up cron pass**.
The engine follows up only `OUTREACH_SENT`/`FOLLOWING_UP` prospects, respects
the max-follow-ups cap, and skips anyone flagged for human review.

### Step 4 — A prospect replies (Tab 4)
Select the prospect in **Simulation target**, click one of the four reply
buttons (rejection / more info / complex question / interest). The intent agent
classifies the reply and routes it:

| Reply | What happens automatically |
|---|---|
| ❌ Rejection / opt-out | Polite farewell; status → `OPT_OUT` — **permanent**, no further contact ever |
| 📄 More info | Auto-reply with real tiers from the knowledge base; flags for a human if classifier confidence < 0.75 |
| 🧠 Complex question | **No** automated reply; 🚨 flags for human takeover; automation pauses |
| 🌟 Interest | Auto-reply with the Cal.com scheduling link; status → `MEETING_PROPOSED` |

A green banner confirms the new status after each simulation.

### Step 5 — Book the meeting (Tab 4)
With the interested prospect in `MEETING_PROPOSED`, click
**🔔 Simulate Cal.com webhook: meeting booked** → `MEETING_CONFIRMED`.
Try the webhook on a prospect in any other state: the system refuses with a
**409** explanation — proof that "link sent" is never counted as "booked".

### Step 6 — Take over a conversation (Tab 3)
Open any prospect's thread (every message is tagged with its detected intent).
To reply as yourself: write in **Manual takeover** → **📨 Send as human agent** —
automation is paused for that prospect (🚨 in the CRM table). Resume with
**▶️ Resume AI automation**. **📬 Check replies now** pulls anything new from
the inbox.

### Step 7 — Prove it to yourself (Tab 4 → audit log)
The **🧾 Audit log** shows every automated decision: `research_run`,
`outreach_sent`, `followups_cancelled_on_reply` (STOP-ON-REPLY firing),
`meeting_confirmed_webhook`, `late_reply_in_terminal_state`, manual takeovers.

---

## 4. Reading the CRM statuses

| Status | Meaning | Who can change it |
|---|---|---|
| `RESEARCHED` → `PENDING_REVIEW` | Discovered, waiting for human review | Research agent |
| `APPROVED` | Human approved the draft | **Human only** |
| `OUTREACH_SENT` | First touch delivered | System (post-approval) |
| `FOLLOWING_UP` | Cadence follow-ups in progress | Follow-up engine |
| `REPLIED` | Prospect answered — automation stands down | Intent agent |
| `INTERESTED` | Positive interest detected | Intent agent |
| `MEETING_PROPOSED` | Scheduling link sent — **not** a booking | Intent agent |
| `MEETING_CONFIRMED` | Webhook confirmed the booking | **Webhook only** (HTTP 409 otherwise) |
| `OPT_OUT` / `REJECTED` | Terminal — no further contact, ever | Intent agent / human |

---

## 5. Resetting between demo runs

`scripts/smoke_test.py` (see §6) rebuilds a canonical demo state:
#1 SeaStack AI `MEETING_CONFIRMED` · #2 KiloCloud `OPT_OUT` · #4 NexusAgents
`HIGH, PENDING_REVIEW` · remaining prospects queued. Alternatively use the
sidebar **Danger zone** reset + Tab 1 research.

## 6. Filming the required demo video (script + shot list)

The brief requires a short video showing research → outreach → follow-ups →
meeting coordination, stating clearly what is real, manual, or simulated.
Suggested 3–4 minute cut:

1. **(0:00) Sidebar + Tab 1** — narrate: "runs fully offline in mock mode, zero
   budget." Click **Run research now**; show the queue appear.
2. **(0:40) Tab 2** — open a HIGH prospect; show reasoning, sources, flags, the
   editable draft; click **Approve**; point at the `OUTREACH_SENT` status in Tab 3.
3. **(1:20) Tab 4** — interest simulation → `MEETING_PROPOSED`. Say plainly:
   "LinkedIn send/receive is simulated with a mock driver — LinkedIn's ToS is the
   blocker; the compliant integration paths are documented in docs/LIMITATIONS."
4. **(1:50) Webhook** — click the booking simulator → `MEETING_CONFIRMED`; then
   click it again on an OPT_OUT prospect to show the 409 refusal.
5. **(2:20) Tab 3** — message log with intent tags; send a manual takeover
   message; point at the 🚨 flag.
6. **(2:50) Opt-out + follow-ups** — run the opt-out simulation on another
   prospect, then trigger the cron pass: nobody who replied receives anything.
7. **(3:20) Tests** — terminal: `pytest tests/` (16 passed) and
   `scripts/smoke_test.py` (12 assertions). Close on the audit log.

## 7. Troubleshooting

| Symptom | Fix |
|---|---|
| Port 8501 busy | `--server.port 8502` (any free port) |
| "Review queue is empty" | Tab 1 → **Run research now** (or reset via Danger zone) |
| Simulation banner didn't appear | It renders at the top of Tab 4 after the automatic refresh — scroll up |
| Webhook simulator returns 409 | Expected unless the prospect is exactly `MEETING_PROPOSED` — that's the rule working |
| Wants a fully fresh database | Danger zone reset → research again |
