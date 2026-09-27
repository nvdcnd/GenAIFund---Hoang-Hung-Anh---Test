# Configuration & Operations Reference

Everything that can be tuned without touching code, plus the exact wiring for
each upgrade path. Zero-config default: no `.env` file at all → mock mode.

---

## 1. Environment variables (copy `.env.example` → `.env`)

| Variable | Default (no .env) | Effect |
|---|---|---|
| `LLM_MODEL` | `openai/gpt-4o-mini` | Model string (LiteLLM-style prefixes tolerated) |
| `OPENAI_API_KEY` | *(empty)* | **Empty = MockLLM.** Any OpenAI-compatible key switches all agents to real structured-output calls |
| `LINKEDIN_DRIVER` | `mock` | `mock` \| `phantombuster` \| `dripify` \| `tinyfish` — see §2 |
| `PHANTOMBUSTER_API_KEY` / `_AGENT_ID` | *(empty)* | Required for the PhantomBuster driver |
| `DRIFIPI_API_KEY` | *(empty)* | Required for the Dripify driver |
| `TINYFISH_API_KEY` | *(empty)* | Required for the TinyFish driver |
| `API_HOST` / `API_PORT` | `127.0.0.1` / `8001` | Webhook listener bind |
| `WEBHOOK_SECRET` | `change-me` | **Set a real value in any shared deployment** — enables 401 + HMAC verification (§4) |
| `CALENDLY_LINK` | `https://cal.com/genai-fund/hackathon-sponsor` | Link sent to interested prospects |
| `DATABASE_URL` | `sqlite:///data/outreach.db` | Swap for Postgres/MySQL URL without code changes |

Rules of thumb: missing driver keys raise loudly at driver construction
(never silently no-op); `WEBHOOK_SECRET=change-me` intentionally means
"disabled" so local demos don't 401.

## 2. Choosing the LinkedIn driver

| Driver | What works today | What you must supply | Best for |
|---|---|---|---|
| **mock** (default) | Everything: fixtures, sends, auto-replies, inbox | nothing | Demos, tests, development |
| **phantombuster** | `send_message` (agent launch), `check_replies` (agent output); `search_prospects` raises with wiring instructions | API key + agent id of a LinkedIn Search Export phantom | The "real-world" reference path; free-trial friendly |
| **dripify** | `send_message`, `check_replies` (campaign actions / conversations) | API key; prospects come from Dripify's own lists | Teams already running Dripify campaigns |
| **tinyfish** | `send_message` (job submit), `check_replies` (inbox jobs) | API key | Marketplace-style automation |

All four implement the same `LinkedInProvider` ABC, so switching is one env
var — agents and UI are untouched. The compliant-integration tradeoffs are in
`docs/LIMITATIONS.md` §2.

## 3. LLM upgrade path

1. `pip` already includes `openai`; set `OPENAI_API_KEY` (and optionally
   `LLM_MODEL=anthropic/claude-3-5-sonnet` via a compatible gateway).
2. Nothing else changes: `generate()` switches from `MockLLM` to structured
   JSON-schema completions validated into the same pydantic models.
3. Failures degrade safely: any LLM error falls back to deterministic
   templates, so outreach never fails mid-send.

Cost note: `gpt-4o-mini` on this workload (classify + short drafts) is
fractions of a cent per prospect; mock mode remains free forever.

## 4. Deploying the webhook listener

Local test:

```bash
.venv/Scripts/python.exe -m uvicorn utils.webhook_handler:app --port 8001
```

Production-ish (Linux box / container behind TLS):

```bash
WEBHOOK_SECRET=$(openssl rand -hex 32) uvicorn utils.webhook_handler:app \
  --host 0.0.0.0 --port 8001 --proxy-headers
```

Then point Cal.com (or Calendly) at
`https://<host>/api/webhook/booking` and configure the secret header
`X-Webhook-Secret` with either the raw secret or
`hex(HMAC_SHA256(secret, raw_body))` — both are accepted (compare_digest).
Endpoint behavior the tests pin down: 200 confirm from `MEETING_PROPOSED`
only, 409 otherwise, 404 unknown prospect, 401 bad/missing secret, 400 bad
JSON, replay-safe idempotency.

## 5. Scheduling the cron pass (production wiring)

The demo triggers cadence via Tab 4 buttons calling exactly the functions a
scheduler would. Minimal APScheduler wiring:

```python
from apscheduler.schedulers.blocking import BlockingScheduler
from database import db_session
from agents import followup_agent, intent_agent
from drivers.factory import get_driver
from database.models import CampaignConfig

drv = get_driver()
sched = BlockingScheduler()

@sched.sinterval(hours=1)  # placeholder — see note below
def poll_replies():
    with db_session.session_scope() as s:
        intent_agent.poll_replies(s, drv)

@sched.sinterval(days=1)
def followup_pass():
    with db_session.session_scope() as s:
        camp = db_session.get_or_create_campaign(s)
        followup_agent.run_followups(s, camp, drv)

sched.start()
```

(Decorator names are illustrative — use `sched.add_job(..., trigger="interval", …)`;
`poll_replies` every minute, `run_followups` daily.) Run this as its own
process — not inside Streamlit — and only one instance at a time.

## 6. Database notes

- **File**: `data/outreach.db` (auto-created by `Base.metadata.create_all` on
  first engine use). Gitignored — it is machine-local state, not source.
- **Reset**: sidebar Danger zone, or delete the file, or run
  `scripts/smoke_test.py` (resets rows and rebuilds the canonical demo state).
- **Backup**: copy the file while the server is stopped, or
  `sqlite3 data/outreach.db ".backup backup.db"`.
- **Enum storage**: values are stored as strings (`'HIGH'`, `'OUTREACH_SENT'`);
  don't rely on column ordinal order when querying directly.
- **Concurrency**: Streamlit + a separate scheduler both open short
  transactions via `session_scope()`; SQLite handles this fine at demo scale.
  Beyond ~a few concurrent writers, switch `DATABASE_URL` to Postgres —
  models are portable (no SQLite-specific columns).

## 7. Repository hygiene

- **Line endings**: `.gitattributes` normalizes all text to LF (`*.bat/*.cmd`
  stay CRLF). Verified: all tracked files are `i/lf w/lf`.
- **Commits are gated**: `git config core.hooksPath .githooks` (one-time per
  clone) makes every commit run the 16-test suite; `--no-verify` bypasses.
- **CI**: `.github/workflows/ci.yml` runs the suite on every push/PR
  (Python 3.13, pip cache). See `.github/REMOTE_SETUP.md` to connect a remote.
- **No secrets in the repo**: `.env` is gitignored; `.env.example` documents
  every variable with safe defaults.
