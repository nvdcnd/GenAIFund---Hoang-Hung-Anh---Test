# What Is Real, What Is Simulated, What Is Manual

The assignment asks for exactly this disclosure — and an evaluator should be
able to trust it. Every claim below was verified against the running system on
2026-09-25 (pytest 16/16, smoke 12/12, live UI).

---

## 1. Fully functional (real, exercised, tested)

| Capability | Proof |
|---|---|
| Research pipeline: discovery, dedupe, priority + written reasoning, review queue | smoke test #1; UI Tab 1→2 |
| Enrichment: degree-aware drafts (≤300 note / ≤1300 DM), sources, uncertainty flags | Tab 2 render; approve-flow pytest |
| HITL approval gate — nothing sends without a human click | `test_approve_button_sends_outreach` |
| Reply intake + intent classification (5 intents) and routing | `test_intent_branches.py` (3 tests) |
| STOP-ON-REPLY — automation structurally cannot touch replied prospects | smoke #5 (0 follow-ups after reply) |
| Opt-out permanence — late replies never re-open contact, still classified + audited | pytest + live UI (`late_reply_in_terminal_state`) |
| Human takeover — pause AI, send as human, resume | Tab 3 buttons; audit trail |
| Cadence engine — caps, delays, no duplicates, skips flagged prospects | `run_followups` + smoke #5 |
| Meeting funnel — `INTERESTED` / `MEETING_PROPOSED` / `MEETING_CONFIRMED` tracked separately | smoke #4/#6; state machine |
| Webhook contract — HMAC/raw secret 401s, 200 confirm, 409 wrong-state, 404 unknown, idempotent replay, 400 bad JSON | `test_webhook_http.py` (8 tests) |
| Audit trail of every automated decision | Tab 4 audit log |
| Priority ordering HIGH→MED→LOW | headless assert + UI |
| Full regression suite + CI + commit gate | 16/16 pytest, workflow + `.githooks/pre-commit` |

## 2. Simulated — and exactly why

**LinkedIn message transport (send/receive) is simulated** by
`MockLinkedInDriver`. This is the one large simulation, it is deliberate, and
the brief explicitly authorizes it (*"If a required capability is unavailable,
explain the blocker and demonstrate that portion in a clearly labeled
simulation"*).

**The blocker.** LinkedIn does not offer an open API for sending DMs or
connection requests. Its official (Tos-compliant) API surfaces are partner-only
("Talent Solutions" tier, procurement-led), and automating the member surface
with bots or unofficial clients violates the LinkedIn User Agreement — risking
account restriction for GenAI Fund. The compliant paths that exist:

1. **PhantomBuster** — commercial middleware operating under its own compliance
   layer (rate caps, human-like pacing). Driver shipped; needs an account,
   API key, and a configured phantom. Free trial available.
2. **Dripify** — campaign-based LinkedIn automation SaaS with an API on paid
   plans. Driver shipped; prospects live in Dripify's lists.
3. **TinyFish** — marketplace-style automation jobs. Driver shipped.
4. **Official LinkedIn partner API** — the long-term enterprise path; requires
   a partnership application (not available within this assignment's window).

**How the simulation is labeled.** The sidebar always shows
`LinkedIn driver: mock`. Every fixture record carries
`flagged_uncertainties: "MOCK DATA: …"` rendered as a warning in Tab 2, and
`*.example` emails make real contact impossible. Sends are stamped
`simulated=True` in the audit log. Nothing about the mock mode pretends to be
real.

**What is NOT simulated:** everything downstream of the transport — matching,
state machine, classification, cadence, webhook verification, persistence,
audit. Swap the driver via `LINKEDIN_DRIVER` and those layers run unchanged.

Also simulated by design (each tiny and labeled): the Cal.com webhook in UI
demos is an in-process call of the same function the HTTP endpoint uses
(the HTTP layer itself is really tested over the wire contract via
`TestClient`); the mock driver auto-generates ~45% mock replies (seeded RNG)
so the reply pipeline demos deterministically; knowledge-base "research" data
is fixture-based in mock mode.

## 3. Manual by design (human-in-the-loop is the product)

- **Approving every send** — the core requirement, not a limitation.
- **Handling `COMPLEX_QUESTION` and low-confidence `REQUEST_MORE_INFO`** — the
  system deliberately does not auto-reply to negotiations; it flags 🚨 and waits.
- **Editing drafts** — optional, one click to regenerate or save.
- **Triggering cadence in demo mode** — a scheduler would call the same
  functions in production (wiring in CONFIGURATION §5).
- **Recording the required demo video** — the only open submission item;
  script in USER_GUIDE §6.

## 4. Known simplifications (safe here, named for honesty)

1. **Single-user dashboard** — no auth on the local Streamlit app. For team
   access, deploy behind SSO/basic-auth reverse proxy or use Streamlit's
   native auth. Acceptable for a take-home prototype; unacceptable in
   production.
2. **SQLite** — right for demo scale; Postgres swap documented (one env var).
3. **Real drivers' `search_prospects` are not implemented** — they raise with
   precise wiring instructions rather than shipping untested API guesses.
   Send/receive for those drivers is real API-mapped code (keyed), but
   unexercised without keys.
4. **Email enrichment is pattern-inferred** in mock mode and flagged as
   unverified — the honest behavior for a prototype.
5. **Fixture dataset is 8 curated SEA AI companies** — illustrative, not a
   live market scan.

## 5. Hardening roadmap (post-assignment, in value order)

1. Scheduler process (APScheduler) for polls + cadence — removes the last
   manual trigger.
2. Auth + multi-reviewer audit identity on the dashboard.
3. Prompt-injection scrubbing of prospect-supplied text before LLM
   classification, plus retries/backoff/cost-caps on LLM calls.
4. Rate-limit pacing + per-day send ceilings in real drivers (LinkedIn safety).
5. Postgres + Alembic migrations when persistence outgrows one file.
6. Webhook source allowlist + signature rotation.
