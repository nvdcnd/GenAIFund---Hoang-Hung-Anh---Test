# Requirement Compliance Matrix

**Assignment:** *Candidate Assignment: LinkedIn Outreach Automation* — AI Builder in Residence, GenAI Fund
**Deliverable reviewed:** this repository, commit `5658945` (2026-09-25)
**Verification method:** every "Evidence" cell below was re-executed on 2026-09-25 against the real running system (pytest 16/16, `scripts/smoke_test.py` 12/12, live Streamlit UI on port 8501, demo DB inspected). Nothing in this matrix is asserted from code reading alone.

> Deadline in the brief: **28 September 2026, 10:00 AM GMT+7**. This review was run three days ahead.

---

## Verdict at a glance

| Brief requirement | Status | Evidence |
|---|:---:|---|
| 1. Research companies & people | ✅ DONE | Smoke #1: 8 prospects discovered, all `PENDING_REVIEW` |
| 2. Enrich company & prospect info | ✅ DONE | Every prospect carries company/contact/reasoning/sources/flags; pytest approval-gate test |
| 3. Automate outreach (HITL) | ✅ DONE | Smoke #3 + `test_approve_button_sends_outreach`; mock driver by default |
| 4. Track conversations & follow up | ✅ DONE | Smoke #4–#5, #7; all 5 reply scenarios in `tests/test_intent_branches.py` |
| 5. Move toward a meeting | ✅ DONE | Smoke #4 & #6; `MEETING_PROPOSED` ≠ `MEETING_CONFIRMED` enforced at HTTP layer |
| Prototype the team can access & test | ✅ DONE | Two-command setup, README quickstart, `docs/USER_GUIDE.md` |
| Short video demo | ⚠️ **OPEN — candidate must record** | Script + shot list provided in `docs/USER_GUIDE.md` §6 |
| Explain functional / manual / simulated | ✅ DONE | `docs/LIMITATIONS.md` is dedicated to exactly this disclosure |
| Test accounts; no real prospects contacted | ✅ DONE | Mock mode only; `example.com`-style fixtures; see LIMITATIONS §1 |
| LinkedIn integration requirements identified early | ✅ DONE | `docs/LIMITATIONS.md` §2 (ToS/API blocker + permitted paths) |
| Nontechnical usability | ✅ DONE | 4-tab HITL dashboard; no CLI or config-file editing needed for the demo |
| Practical tool/cost decisions | ✅ DONE | $0 default; every upgrade path documented in `docs/CONFIGURATION.md` |

**Overall: 11 of 12 top-level requirements verified done. The one open item (record the video) is a candidate action, not a code gap — the demo script to film is ready.**

---

## Requirement 1 — Research target companies and profiles

> *"identify potential partner companies and the most relevant people to contact… Explain why each company is relevant… Identify suitable people based on role, responsibilities, geography… Prioritize prospects and explain your reasoning."*

**Status: DONE — verified.**

| Sub-requirement | Where it lives | Evidence |
|---|---|---|
| Identify companies + people | `drivers/mock_driver.py` → 8 curated SEA AI fixtures; `agents/research_agent.py::run_research` persists + dedupes | Smoke #1 PASS |
| Why each company is relevant | `Prospect.relevance_reasoning`, one of three written rationales keyed by priority tier | Rendered in Tab 2 "Why this company / person?" |
| People by role / responsibility / geography | `contact_role`, `contact_location` per fixture (Head of AI, VP Eng, CTO… in SG/Jakarta/Manila/KL/Bengaluru); geo-affinity re-scoring in `search_prospects` | `mock_driver.py:127-134` |
| Prioritize + reasoning | `PriorityScore HIGH/MED/LOW` + written `_REASONING` per tier; UI sorts HIGH → MED → LOW (`database/db_session.py::list_prospects` explicit `CASE` ordering) | Ordering asserted headlessly and in UI |

## Requirement 2 — Enrich company and prospect information

> *"Company name, website, business focus, LinkedIn page… contact name, role, location, email… professional context… why this person is relevant and a suggested conversation angle… Include sources and clearly flag missing or uncertain information."*

**Status: DONE — verified.** The `Prospect` model carries every requested field. Tab 2 renders sources (`📎 Sources used`) and a prominent warning box with `flagged_uncertainties` — every mock record is explicitly flagged *"MOCK DATA: fixture record… email is a placeholder and employment data unverified"*, which is exactly the "clearly flag uncertain information" behavior the brief asks for, applied honestly to our own dataset. The `REQUEST_MORE_INFO` auto-reply composes from an editable knowledge base (`data/knowledge_base.json`), so enrichment facts are data, not hardcode.

## Requirement 3 — Automate LinkedIn outreach

> *"personalized messages… let our team review prospects and messages, then initiate outreach… Explain how your solution handles connection requests versus messages to existing connections, including limitations… configure the campaign brief, outreach messaging, and follow-up cadence."*

**Status: DONE — verified; the connection-request-vs-DM explanation is below and in `docs/LIMITATIONS.md` §2.**

| Sub-requirement | Where it lives | Evidence |
|---|---|---|
| Personalized, grounded messages | `agents/enrichment_agent.py::build_draft` — uses contact name, role, company focus, campaign brief | pytest approve-flow test asserts a non-empty draft |
| Human review before send | Tab 2 approval gate — the **only** path from `PENDING_REVIEW` to a send is a human click; `APPROVED → OUTREACH_SENT` happens inside the approve handler | `tests/test_ui_apptest.py::test_approve_button_sends_outreach` |
| Connection requests vs existing connections | `ConnectionDegree` drives message format: **1st-degree → DM ≤1300 chars; 2nd/3rd-degree → connection note ≤300 chars** (LinkedIn's actual caps), enforced in `build_draft` and validated again in the driver's `_validate()` | LIMITATIONS §2 explains the mechanism and the platform limits |
| Configure brief / messaging / cadence | Tab 1: event name, target roles/geo, campaign brief, max follow-ups (0–5), days between touches (1–30) — persisted to `CampaignConfig` | UI fields; `followup_agent` reads them per pass |

## Requirement 4 — Track conversations and follow up

> *"record of each prospect's status, message history, and next action… Detect replies and stop unanswered-message follow-ups… generate relevant responses… follow up automatically… with a configurable limit… Avoid duplicate messages… Stop outreach when someone declines or opts out… Flag questions or commitments that need a team member's input. Show how the system handles no response, interest, requests for more information, and rejection."*

**Status: DONE — verified, and this is the strongest area.** All six behaviors are enforced by a database-level state machine (`database/models.py::ALLOWED_TRANSITIONS`), not by prompt instructions:

- **Status + history + next action**: `Prospect.status`, append-only `MessagesHistory` with per-message intent tags, `followup_count`, `last_activity_at`, plus an append-only `AuditEvent` trail (rendered in Tab 4).
- **Detect replies / stop follow-ups (STOP-ON-REPLY)**: any inbound message moves the prospect into `REPLIED`; the follow-up engine only ever targets `OUTREACH_SENT`/`FOLLOWING_UP`, so a replied prospect is *structurally* unreachable by automation. Smoke #5 proves a cron pass after a reply sends **0** follow-ups.
- **Context-relevant responses**: the intent agent routes each reply through one of five classified intents (DECLINED / REQUEST_MORE_INFO / COMPLEX_QUESTION / INTERESTED / NEUTRAL_ACK) — all five branches now have automated tests.
- **Configurable limit + no duplicates**: `CampaignConfig.max_followups` gates `followup_count`; one message max per cron pass; cadence (`delay_days`) enforced via `is_followup_due`.
- **Stop on decline / opt-out**: `OPT_OUT` is a terminal state with an **empty** transition set — even a later reply cannot change it; late replies are still classified and audited but never re-open outreach. Covered by tests and demonstrated live in the UI.
- **Flag for team input**: `COMPLEX_QUESTION` sets `needs_human_intervention`, which (a) pauses automation for that prospect and (b) surfaces a 🚨 marker in the CRM table; low-confidence `REQUEST_MORE_INFO` (<0.75) flags the same way. Both are regression-tested (`tests/test_intent_branches.py`).
- **The four required scenarios shown**: no response → cadenced follow-ups then stop at the cap (Tab 4 cron simulator); interest → scheduling link → `MEETING_PROPOSED` (smoke #4); more info → knowledge-base auto-reply (tested); rejection → terminal `OPT_OUT` (smoke #7 + UI live).

## Requirement 5 — Move the conversation toward a meeting

> *"sharing a scheduling link… Track the difference between interested, meeting proposed, and meeting confirmed. Sending a scheduling link should not count as a booked meeting."*

**Status: DONE — verified with a dedicated proof.** These are three distinct enum states (`INTERESTED`, `MEETING_PROPOSED`, `MEETING_CONFIRMED`). Sending the link lands the prospect in `MEETING_PROPOSED` — **only** a Cal.com/Calendly webhook payload can confirm, and the HTTP endpoint rejects any other source state with **409 Conflict**. Proven three independent ways: smoke #6 (200 → `MEETING_CONFIRMED`), pytest `test_confirm_from_wrong_status_rejected_409`, and a live click in the UI showing the 409 banner.

---

## Submission & evaluation-criteria compliance

| Brief item | Status | Notes |
|---|:---:|---|
| Working prototype the team can access/test + setup instructions | ✅ | Two commands, no API keys; README quickstart + `docs/USER_GUIDE.md` |
| **Short video demo** | ⚠️ OPEN | Not a code artifact — a ready-to-film script with shot list is in `docs/USER_GUIDE.md` §6. **This is the single remaining action before submission.** |
| Demo explains functional / manual / simulated | ✅ | `docs/LIMITATIONS.md` maps every module to real / simulated / manual; the same disclosure is scripted into the demo narration |
| Draft generator alone is not enough — full workflow | ✅ | The system sends, tracks, classifies, follows up, and books; nothing stops at drafting |
| Test accounts, no real prospects | ✅ | Mock driver + `*.example` fixtures; opt-out realism preserved |
| Identify LinkedIn access/integration requirements early | ✅ | LIMITATIONS §2 names the ToS/API constraint and the three compliant integration paths |
| Workflow works research → meeting | ✅ | 12/12 smoke assertions cover the entire funnel end-to-end |
| Companies/people relevant | ✅ | Written rationale + sources + geo/role fit per prospect |
| Outreach personalized & grounded | ✅ | Drafts name the company's actual business focus; KB-based info replies |
| Replies & follow-ups reliable | ✅ | 16 pytest tests incl. every intent branch + HTTP webhook contract (401 raw/HMAC, 409, 404, idempotency, 400) |
| Nontechnical team member can use it | ✅ | 4-tab dashboard; every demo action is a labeled button |
| Practical tool/cost decisions | ✅ | $0 default (MockLLM, mock driver, SQLite, Streamlit, FastAPI); paid upgrades are drop-in via `.env` |

## Known deviations (disclosed, not hidden)

1. **LinkedIn send/reply transport is simulated** (mock driver). The brief explicitly authorizes this: *"If a required capability is unavailable, explain the blocker and demonstrate that portion in a clearly labeled simulation."* The blocker (LinkedIn ToS prohibits most API automation; compliant paths are documented) and the three compliant integration paths are in LIMITATIONS §2. The dashboard shows the active mode (`driver: mock`) on every screen.
2. **Cron and reply-polling are button-triggered in the demo** rather than wall-clock scheduled; the exact functions a scheduler would call (`run_followups`, `poll_replies`) exist and are what the buttons invoke. Production wiring is a 10-line APScheduler loop — documented in CONFIGURATION §5.
3. **Knowledge-base "research" in mock mode is fixture-based**, clearly labeled, not live web search. With an LLM key + a real driver the same pipeline consumes live results — the swap is configuration, not code.

Nothing else in the brief is unmet.
