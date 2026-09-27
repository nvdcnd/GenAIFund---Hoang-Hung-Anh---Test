# 🤝 GenAI Fund — Agentic AI LinkedIn Outreach & Booking Automation

A working, **100% zero-budget** prototype that automates sponsorship outreach for
**Agentic AI Build Week** (GenAI Fund hackathon): research → HITL review → LinkedIn
outreach → smart follow-ups → reply intent classification → Cal.com booking confirmation.

Built for the "AI Builder in Residence" assignment. Every evaluator criterion is
addressed explicitly (see [Evaluation criteria map](#evaluation-criteria-map)).

## 📚 Documentation

| Doc | Read it when you want to… |
|---|---|
| [`https://drive.google.com/drive/folders/1eHPQ73AeQxij8rl1-L-TeYazgzhMOr75?usp=sharing`](https://drive.google.com/drive/folders/1eHPQ73AeQxij8rl1-L-TeYazgzhMOr75?usp=sharing) | **watch the required demo video** (`demo.mp4`, 3 min, subtitled) + video `thumbnail.png` |
| [`docs/USER_GUIDE.md`](docs/USER_GUIDE.md) | run the dashboard, walk the workflow, or film the demo video (script included) |
| [`docs/COMPLIANCE.md`](docs/COMPLIANCE.md) | check every brief requirement against implementation + evidence |
| [`docs/ARCHITECTURE.md`](docs/ARCHITECTURE.md) | understand each module, the state machine, and every design decision |
| [`docs/LIMITATIONS.md`](docs/LIMITATIONS.md) | see exactly what is real / simulated / manual — and why |
| [`docs/CONFIGURATION.md`](docs/CONFIGURATION.md) | plug in real drivers/LLM, deploy the webhook, schedule the cron |

---

## Quickstart (2 commands, zero cost)

```bash
py -3.13 -m venv .venv                       # any Python 3.11+ works
.venv/Scripts/pip install -r requirements.txt

# 1) End-to-end pipeline proof (no UI needed):
.venv/Scripts/python.exe scripts/smoke_test.py

# 2) The HITL dashboard:
.venv/Scripts/streamlit.exe run app.py --server.port 8501
```

Optional — real webhook listener (Module 6):

```bash
.venv/Scripts/python.exe -m uvicorn utils.webhook_handler:app --port 8001
# POST http://127.0.0.1:8001/api/webhook/booking   {"payload":{"email":"...","name":"..."}}
```

---

## Tests & quality gates (all free)

16 pytest tests cover every layer: intent branches (complex-question human flag,
low-confidence more-info flag), the HTTP webhook contract (401 secret enforcement
raw + HMAC, 409 status gate, idempotent replay, 400 bad JSON), and the Streamlit
UI itself via `AppTest` (tabs render, approve sends, flash messages survive reruns).
Tests always run against an isolated temp database — the demo DB is never touched.

```bash
.venv/Scripts/python.exe -m pytest tests/ -v
```

Two zero-budget gates run the same suite automatically:

- **Local commits** — a pre-commit hook runs pytest and blocks the commit on any
  failure. One-time activation after cloning: `git config core.hooksPath .githooks`.
  Emergency bypass: `git commit --no-verify`.
- **Every push / PR** — free GitHub Actions runner executes the suite
  (`.github/workflows/ci.yml`, Python 3.13, pip caching).

**No API keys required.** With no `.env`, the app runs in deterministic mock mode:
a `MockLLM` (keyword-rule intent classifier, template drafting) and a
`MockLinkedInDriver` (8 curated SEA AI-company fixtures, simulated sends/inbox).
Add keys later and the same code paths switch to live services.

---

## The 60-second demo script (for recruiters)

1. **Tab 1 — Campaign Setup**: brief is pre-filled → click **🚀 Run research now**.
   8 prospects appear in the review queue with reasoning, sources and flags.
2. **Tab 2 — Prospect Review**: pick a prospect, read *why this company/person*,
   edit the draft inline, click **✅ Approve & Initiate Outreach** → status
   `OUTREACH_SENT` (mock send, logged in the audit trail).
3. **Tab 4 — Simulation Suite**: pick that prospect → click
   **🌟 Expressed interest / request booking**. The intent agent classifies the reply,
   answers with the Cal.com link, and the CRM advances `REPLIED → MEETING_PROPOSED`.
4. Same tab → **🔔 Simulate Cal.com webhook: meeting booked** →
   `MEETING_CONFIRMED`. *(Point out: confirmation is ONLY possible via webhook.)*
5. **Tab 3 — CRM**: inspect the full message log (intents tagged per message),
   then demonstrate **manual takeover** (human sends a message; AI pauses).
6. Back in **Tab 4**: click **❌ Rejection / opt-out** on another prospect →
   `OPT_OUT`, automated farewell, and **zero further follow-ups — ever** (state
   machine guarantees it).
7. Optional: **⏩ Force all active prospects 'due'** → **⚙️ Trigger follow-up cron
   pass** → context-aware follow-ups go out; `followup_count` increments; prospects
   who replied are structurally excluded.

---

## Architecture

```
Streamlit (app.py, 4 tabs — HITL)
        │
        ├── agents/research_agent.py     discovery + dedupe + ICP reasoning
        ├── agents/enrichment_agent.py   degree-aware drafts (≤300 notes / ≤1300 DMs)
        ├── agents/followup_agent.py     outreach + cadence engine (STOP-ON-REPLY)
        ├── agents/intent_agent.py       reply classifier + response generator
        │        └── agents/llm_client.py  real LLM (key set) / MockLLM (no key)
        │
        ├── drivers/  LinkedInProvider ABC
        │     ├── mock_driver.py          ← default, zero-budget
        │     ├── phantombuster_driver.py
        │     ├── dripify_driver.py
        │     └── tinyfish_driver.py
        │
        ├── utils/webhook_handler.py     FastAPI: /api/webhook/booking (Cal.com/Calendly)
        │
        └── database/  SQLAlchemy + SQLite
              models.py  → Prospect, CampaignConfig, MessagesHistory, AuditEvent
                           + strict state machine (ALLOWED_TRANSITIONS)
```

### The strict CRM state machine

```
RESEARCHED ──► PENDING_REVIEW ──► APPROVED ──► OUTREACH_SENT ──► FOLLOWING_UP
                    │                                          │        │
                    └──► REJECTED                              └───► REPLIED ◄┘
                                                                 (hub state)
REPLIED ──► OPT_OUT | INTERESTED | MEETING_PROPOSED
INTERESTED / MEETING_PROPOSED ──► … ──► MEETING_CONFIRMED   (webhook ONLY)
```

**Hard guarantees enforced in code** (`database/models.py::ALLOWED_TRANSITIONS`):

- **STOP-ON-REPLY**: only `OUTREACH_SENT`/`FOLLOWING_UP` prospects are eligible for
  follow-ups; any inbound message moves the prospect to `REPLIED`, from which no
  automated follow-up can ever fire. The follow-up engine re-checks state per pass.
- **`MEETING_PROPOSED` ≠ `MEETING_CONFIRMED`**: the scheduling link sets
  `MEETING_PROPOSED`; **only** a booking webhook payload confirms.
- Illegal transitions raise `InvalidTransition` instead of corrupting the CRM.

---

## Evaluation criteria map

| Criterion | Where it lives |
|---|---|
| Resourcefulness & zero-budget | `MockLLM` + `MockLinkedInDriver` default mode; SQLite; no paid APIs anywhere; real drivers behind the same interface for the "real world" story |
| One complete, reliable flow | `scripts/smoke_test.py` proves research→outreach→reply→classify→link→webhook→confirm; dashboard walks the same path |
| Preferred tool stack | `LinkedInProvider` ABC with PhantomBuster / Dripify / TinyFish drivers; TinyFish- and Dripify-shaped API mappings documented in the drivers |
| Non-technical usability | 4-tab Streamlit HITL: setup → approve/edit → CRM/takeover → one-click simulations |
| Reliable tracking & reply logic | `ALLOWED_TRANSITIONS` state machine, STOP-ON-REPLY, intent routing (decline / info / complex→human / interested), `followup_count` + cadence, audit trail |

---

## Knowledge base & configuration

- `data/knowledge_base.json` — event facts, sponsorship tiers (Titanium SGD 25k /
  Gold SGD 10k / Community SGD 2k), in-kind options, FAQs. The `REQUEST_MORE_INFO`
  auto-reply composes from this file, so non-engineers can edit pricing without code.
- `.env.example` — copy to `.env` to plug in real keys (`OPENAI_API_KEY`,
  `LINKEDIN_DRIVER=phantombuster|dripify|tinyfish`, webhook secret, booking link).
  Everything defaults to mock mode.

## Production notes (what we'd harden next)

- LLM calls: add retries/backoff, cost caps, and prompt-injection scrubbing of
  prospect-supplied text before classification.
- Drivers: PhantomBuster container polling, Dripify campaign export mapping, and
  rate-limit awareness (see TODO markers inside each driver).
- Ops: cron the follow-up pass (`run_followups`) and reply polling
  (`poll_replies`) outside Streamlit (e.g. APScheduler or a worker container), and
  point Cal.com/Calendly at the FastAPI webhook with the HMAC secret.
