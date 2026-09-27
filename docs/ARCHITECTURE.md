# Architecture — how every piece works and why it is built that way

Companion documents: `docs/COMPLIANCE.md` (requirement mapping),
`docs/USER_GUIDE.md` (click-path manual), `docs/CONFIGURATION.md` (env/driver/LLM
setup), `docs/LIMITATIONS.md` (real vs simulated vs manual).

---

## 0. One-paragraph summary

Four agent modules (research, enrichment, intent, follow-up) push a CRM of
prospects through a **strict, database-enforced state machine** toward booked
meetings, exchanging messages through a swappable **LinkedInProvider** driver
(mock by default, PhantomBuster/Dripify/TinyFish behind env keys), under a
Streamlit dashboard where a human approves every send and can pause or take over
any conversation. A FastAPI webhook is the only thing that can confirm a
meeting. SQLite keeps all state; every automated decision lands in an
append-only audit trail.

## 1. Layer map

```
app.py (Streamlit, 4 tabs)            ← the ONLY place humans act
   │
   ├── agents/research_agent.py       ← Module 1: discovery + dedupe + priority
   ├── agents/enrichment_agent.py     ← Module 2: degree-aware drafts ≤300/≤1300
   ├── agents/intent_agent.py         ← Module 5: reply classifier + router
   ├── agents/followup_agent.py       ← Module 4: outreach + cadence engine
   │      └── agents/llm_client.py    ← real LLM when keyed / MockLLM otherwise
   │
   ├── drivers/LinkedInProvider (ABC) ← one interface, four implementations
   │      ├── mock_driver.py          ← default: fixtures + in-memory inbox
   │      ├── phantombuster_driver.py ← API-keyed
   │      ├── dripify_driver.py       ← API-keyed
   │      └── tinyfish_driver.py      ← API-keyed
   │
   ├── utils/webhook_handler.py       ← FastAPI :8001 — the ONLY confirmer
   │
   └── database/
          models.py      ← Prospect, MessagesHistory, AuditEvent, CampaignConfig
                            + ALLOWED_TRANSITIONS + set_status() validator
          db_session.py  ← transactional scope + query helpers
          SQLite file    ← data/outreach.db (gitignored)
```

Dependency rule: arrows only point downward. Agents never import Streamlit;
drivers never import agents; the webhook never imports Streamlit. This is why
pytest can exercise every business rule headlessly and AppTest can drive the UI
without changing any of them.

## 2. The CRM state machine (the heart of the system)

`database/models.py` defines every legal transition:

```
RESEARCHED ──► PENDING_REVIEW ──► APPROVED ──► OUTREACH_SENT ──► FOLLOWING_UP
                    │                                          │         │
                    └──► REJECTED (terminal)                   └──► REPLIED ◄┘
                                                                 (hub)
REPLIED ──► OPT_OUT (terminal) | INTERESTED | MEETING_PROPOSED | OUTREACH_SENT*
INTERESTED ──► MEETING_PROPOSED ──► MEETING_CONFIRMED (webhook only)
MEETING_CONFIRMED ──► OPT_OUT | REPLIED          (* no-op classifier return)
```

Three design decisions worth understanding:

1. **The machine is enforced, not advisory.** Every status change funnels
   through `Prospect.set_status()`, which consults `ALLOWED_TRANSITIONS` and
   raises `InvalidTransition` on anything illegal. Tests prove that even our
   own test code cannot jump `OUTREACH_SENT → MEETING_PROPOSED`.
2. **STOP-ON-REPLY is structural.** The follow-up engine's eligibility check
   (`db_session.is_followup_due`) only ever returns true for `OUTREACH_SENT` /
   `FOLLOWING_UP`. A reply moves the prospect to `REPLIED` — a state follow-ups
   can never target — so "never follow up after a reply" doesn't depend on a
   flag being remembered; the state space itself forbids it.
3. **Terminal states are truly terminal.** `OPT_OUT` and `REJECTED` have empty
   transition sets. A late reply from an opted-out prospect is still classified
   and written to the audit log (so nothing is silently dropped), but wrapped in
   `try/except InvalidTransition` so it cannot re-open contact.

## 3. Module deep-dives

### 3.1 Research agent (`agents/research_agent.py`)
`run_research(session, campaign)` queries the driver's `search_prospects()`,
**dedupes** on `(company_linkedin, contact_name)` — backed by a DB unique
constraint, so a race can't double-insert — writes a baseline draft via the
enrichment agent, persists, then walks each new prospect
`RESEARCHED → PENDING_REVIEW` through the legal transition, and logs
`research_run` to the audit trail. In mock mode the driver returns 8 curated
SEA fixtures with priority-tier reasoning; with a real driver the same code
consumes live results.

### 3.2 Enrichment agent (`agents/enrichment_agent.py`)
`build_draft()` is **degree-aware**: 1st-degree connections get a DM shaped for
LinkedIn's ≤1300-char inbox; 2nd/3rd-degree get a connection note hard-trimmed
to ≤300 chars (LinkedIn's invite cap). Templates name the company's actual
business focus and the event. When an LLM key is set, `generate()` returns a
validated `DraftOutput` that replaces the template — but any failure falls back
to the deterministic template, so the demo can never break mid-pitch.
`enrich()` also backfills `sources` and a `flagged_uncertainties` string (never
overwriting existing flags).

### 3.3 Intent agent (`agents/intent_agent.py`) — Module 5
`process_inbound()` runs one reply through: match prospect by email→name→
fuzzy-first-token → log the raw message → STOP-ON-REPLY transition → classify
→ route:

| Intent | Handler | State effect | Automation effect |
|---|---|---|---|
| DECLINED | farewell auto-reply | → `OPT_OUT` (terminal) | contact ends permanently |
| REQUEST_MORE_INFO | KB-composed auto-reply (tiers, dates, link) | stays `REPLIED` | flags human if confidence < 0.75 |
| COMPLEX_QUESTION | "HUMAN REVIEW REQUIRED" notice, no auto-reply | stays `REPLIED` | `needs_human_intervention = True` |
| INTERESTED | Cal.com link auto-reply | → `INTERESTED` → `MEETING_PROPOSED` | — |
| NEUTRAL_ACK | logs only | stays `REPLIED` | cadence may resume |

`classify()` calls the LLM client; MockLLM classifies by deterministic keyword
rules (and is regression-tested). `poll_replies()` drains the driver's inbox —
in production this is what a scheduler calls every minute.

### 3.4 Follow-up agent (`agents/followup_agent.py`) — Module 4
`send_outreach()` is the **only** sender of first touches and demands `APPROVED`
state, else raises — the HITL gate in code. It delegates delivery to the driver
(which re-validates length), logs the message, and transitions to
`OUTREACH_SENT`. `run_followups()` is the cron pass: filter by
`is_followup_due` (state ∈ {OUTREACH_SENT, FOLLOWING_UP}, `followup_count <
max_followups`, cadence elapsed, not flagged for human), **re-check state inside
the loop** (a reply may land mid-pass), compose a non-pushy template, send once,
increment `followup_count`, set `FOLLOWING_UP`, audit. Guarantees: STOP-ON-REPLY
(structural), cap respected, no duplicates in a pass, cadence respected.

### 3.5 LLM client (`agents/llm_client.py`)
Single `generate(prompt, schema, system)` entry point. No key → `MockLLM`:
keyword-rule intent classification and template outputs, fully deterministic —
this is what makes tests and demos reproducible for $0. Key set → OpenAI-SDK
chat completion with **strict JSON-schema** structured output validated into
pydantic models (`ResearchOutput`, `DraftOutput`, `IntentOutput`,
`FollowupOutput`). Swapping models is one env var (`LLM_MODEL`).

### 3.6 Drivers (`drivers/`)
One abstract surface — `search_prospects / send_message / check_replies` plus
shared `_validate()` (length caps, empty-message guard). The factory
(`drivers/factory.py`) resolves `LINKEDIN_DRIVER` and imports real drivers
lazily so missing keys never break mock mode. The mock driver also simulates
replies (seeded RNG, ~45% of sends) so the full reply pipeline demos itself;
its `queue_inbound()` is what the dashboard's simulation buttons feed.

### 3.7 Webhook (`utils/webhook_handler.py`) — Module 6
FastAPI app with three routes: `GET /health`, `POST /api/webhook/booking`
(the real endpoint), `POST /api/webhook/booking/simulate` (test helper).
Security: when `WEBHOOK_SECRET` is set (≠ `change-me`), requests must present
either the raw secret or an **HMAC-SHA256 signature of the raw body** —
verified with `hmac.compare_digest`. `process_booking()` matches the payload
(email → name), is **idempotent** for repeat confirmations, returns **404**
for unknown prospects, and **409** for any status other than
`MEETING_PROPOSED`. Only then `MEETING_PROPOSED → MEETING_CONFIRMED` + audit.
This endpoint is the sole confirmer in the system — the dashboard button calls
the same function, so UI and HTTP cannot diverge.

### 3.8 Persistence (`database/`)
Four tables. `Prospect` carries the full research dossier + pipeline state +
`needs_human_intervention` + `followup_count`; unique constraint on
`(company_linkedin, contact_name)`. `MessagesHistory` is append-only with
per-message `intent_detected` and `is_automated`. `AuditEvent` is the
compliance trail (every automation decision, webhook receipt, takeover).
`CampaignConfig` holds brief + cadence. Enums are stored as **strings**
(`values_callable`) — which is why priority ordering uses an explicit SQL
`CASE` rank (HIGH→MED→LOW) rather than relying on alphabetical or ordinal
column order. All sessions run through `session_scope()` (commit/rollback/
close), so a mid-flow exception can never leave half-written state.

## 4. The Streamlit layer (`app.py`)

One file, four tabs, ~370 lines — deliberately thin: it only renders state and
calls into agents/db helpers on button clicks. Each rerun opens a fresh
`session_scope()`; widgets are the single source of transient UI state. Two
patterns worth knowing when editing it:

- **Flash messages**: a handler that will call `st.rerun()` stores its result
  in `st.session_state["tab3_flash"|"tab4_flash"]`; the top of the tab pops
  and renders it on the next run. (A bare `st.success` before `st.rerun()`
  is wiped before anyone can read it.)
- **Cached driver**: `st.cache_resource` keeps one mock-driver instance alive
  per server process, so the simulated inbox persists between interactions.

## 5. Testing strategy (`tests/`)

16 pytest tests across three files, all against an **isolated temp SQLite DB**
(conftest sets `DATABASE_URL` before any project import; the demo DB is never
touched and this is asserted after runs):

- `test_intent_branches.py` — the five-way reply router incl. the two subtle
  branches: complex-question human flag and the <0.75 confidence gate.
- `test_webhook_http.py` — the real FastAPI app via `TestClient`: 401 (missing/
  wrong secret), 200 via HMAC **and** raw secret, 409 wrong-state, 404 unknown,
  idempotent replay, 400 bad JSON. Reaching `MEETING_PROPOSED` is done through
  the real reply pipeline because the state machine (correctly) refuses the
  shortcut.
- `test_ui_apptest.py` — Streamlit's `AppTest` drives `app.py` itself: tabs
  render, the approve button truly sends, flash messages survive `st.rerun()`,
  and the audit grid tolerates mixed id/— rows (a past crash).

`scripts/smoke_test.py` is the 12-assertion end-to-end story (research → … →
confirm + decline) that also resets the demo DB to its canonical state.

## 6. Deliberate simplifications

Honesty about corners cut on purpose (each is safe for the assignment's scope):
single-user (no auth on the dashboard); SQLite over Postgres; the scheduler is
a button in demo mode; the three real drivers' `search_prospects` raise
`NotImplementedError` with instructions rather than shipping untested API
guesses; email addresses in fixtures are `*.example` placeholders. The seams
where each of these would be replaced are named in `docs/CONFIGURATION.md`.
