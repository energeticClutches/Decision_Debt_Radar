# Day 6 Implementation Brief: Decision Workspace (product experience)

**Status:** APPROVED (2026-10-09). The Day-6 design review was accepted, and the Product Owner (PO) froze four decisions (§1). Everything here is binding. Where this brief is silent, choose the most conservative reading and record it in the Day-6 notes. Do not invent methodology.

**Baseline:** commit `cef7a05` (Day 5 complete), Alembic head `0006`, 677 passed and 2 live tests skipped, manifest 33/33.

> All FitConnect data is synthetic. DDI is a transparent evidence-risk heuristic: **higher = more evidence debt (weaker support)**. It is not a probability that the decision is wrong. The LLM never makes or recommends the business decision. "Validated" means *the assessment passed review*, not that the decision is correct.

---

## 0. Hard rules

- **Frozen code: zero diff against `cef7a05`** in:
  - `backend/app/domain/ddi/**`, `backend/app/domain/nbe/**`, `backend/config/ddi/**`, `backend/config/nbe/**`;
  - `backend/app/analytics/**` (DQ, heterogeneity, experiments, SQL guard), `backend/app/customer/**` and `backend/app/synthesis/validators.py`;
  - `backend/app/services/lifecycle.py`;
  - `database/sql/0001`–`0006`.
- **New SQL only in a new migration `0007`, and only if essential.** Prefer none: every N-item below is a read model.
- **No new lifecycle states, agents, authentication, background workers, chart libraries, state libraries or Markdown/HTML renderers.**
- **No new frontend runtime dependencies.** Allowed dev dependencies: `vitest`, `@playwright/test` (plus its Chromium download).
- **The frontend never computes DDI, NBE, direction, stance or permissions.** It only displays stored values. Its permission map is for hiding or disabling buttons only; the server stays authoritative.
- **Untrusted content is never rendered as HTML.** This covers customer quotes, LLM text and `brief.markdown`. No `dangerouslySetInnerHTML` anywhere; a grep test enforces it.
- **Power BI is not built on Day 6.** It moves to Day 7 (§1).
- Do not commit or push. Leave the changes uncommitted.
- Write UTF-8 files without a BOM.

## 1. Frozen decisions

| # | Decision |
|---|---|
| D6-01 | **LLM demo mode = replay.** `DDR_LLM_MODE=live\|replay\|off`. Local and demo default is `replay`. No API key is needed for the standard demo. |
| D6-02 | **Backend N1–N8 approved** (§3). |
| D6-03 | **Power BI moves to Day 7.** Add to the PRD §20 plan a dated amendment note: *"Power BI portfolio analytics is intentionally deferred to Day 7 to keep Day 6 focused on the core Decision Workspace."* Repeat it in the Day-6 notes. Keep every reporting view. |
| D6-04 | **Frontend tests:** Vitest for pure logic, Playwright for the four scenario journeys. |
| D6-05 | **Trust rules (P0):** <ul><li>a stale assessment never looks current;</li><li>a gated assessment never shows a DDI number, band, chart, contribution value or placeholder score anywhere in the DOM;</li><li>`previous_scored_assessment` only ever appears as "vN, superseded", never as the headline.</li></ul> |

## 2. Replay mode (N7) architecture

- **Settings:** `DDR_LLM_MODE` in `backend/app/core/config.py` and `.env.example`.
  - `live` needs `ANTHROPIC_API_KEY` and uses `AnthropicClient`.
  - `off` gives no client (the Day-5 behaviour without a key).
  - `replay` uses a `ReplayDemoClient` in `backend/app/llm/replay.py`.
- **Fixtures live in `backend/demo_fixtures/`** (JSON, `-text` in `.gitattributes`). Product code **never imports from `tests/`**.
  - `classify/`: one recorded response per classification request, keyed by `input_sha256`.
    - They are **generated once** by `scripts/build_demo_fixtures.py`, a dev tool that may import the test stub classifier.
    - Each file carries `"provenance": "stub_not_model_output"` and model `stub:keyword_rules_v1`.
    - The script also checks that every classification request the four scenarios produce at the as-of date has a fixture.
  - `synthesize/` and `review/`: copies of the Day-5 hand-authored scenario fixtures (symbolic evidence selectors resolved at request time, as in `RecordedClient`), with the same provenance.
- **Contracts.** `ReplayDemoClient` implements `LlmClient` exactly. Everything after it runs unchanged: the validators, `agent_runs` metadata, review enforcement, the code findings and the lifecycle.
  - A missing fixture raises the existing `fixture_missing` error, which becomes a recorded failure. It never invents output.
- **Provenance exposed by the API:**
  - every synthesis, review and customer-evidence classification summary includes `provenance` (`live_model_output` | `stub_not_model_output` | `recorded_model_output`) and `model`;
  - `GET /health` (or `/me`) includes `llm_mode`.

  The UI shows **"Replayed demo fixture, not live model output"** wherever provenance is not `live_model_output`.
- **Tests keep their semantics.** The test configuration forces `DDR_LLM_MODE=off` unless a test injects a client. A new test covers replay mode end to end on one scenario.

## 3. Backend read models (N1–N6, N8)

| # | Change |
|---|---|
| N1 | **`GET /assessments/{id}/reviews`**: a list, ordered by `created_at`. Fields: `id`, `assessment_id`, `synthesis_id`, `agent_run_id`, `reviewer_type`, `reviewer_id`, `verdict`, `human_response`, `created_at`, `provenance`, `model_fallback`, and `findings[]`. Each finding: `category`, `severity`, `severity_model`, `source` (model\|code), `target_type`, `target_id`, `target_local_id`, `rationale`, `evidence_ids`, `notes`. Read permission as the other GETs. |
| N2 | **`GET /decisions/{id}/decision-record`**: the latest record, or 404 if none. |
| N3 | **`GET /assessments/{id}/briefs`**: a list of `{id, kind, version, label, synthesis_id, created_at}`. |
| N4 | **`GET /assessments/{id}/traceability`**: the rows of `v_traceability_matrix` for that assessment, **including gap rows**, with the view's columns. No new scoring. |
| N5 | **`DecisionOut` additions:** <ul><li>`stale_reason` and `stale_at`, from the **latest `assessment.stale` audit row** of the decision (null when `assessment_stale` is false);</li><li>`pending_approvals` (an int: proposed customer evidence items).</li></ul> |
| N6 | **`GET /metrics`** (read-only: id, name, definition, unit if present). **`EvidenceOut` additions:** `source_name`, `reliability_tier`, `freshness`. Freshness comes from the existing `v_evidence_freshness` / Day-3 freshness factor; reuse it, don't redefine it. |
| N8 | **`scripts/demo_prepare.py`**: see below. |

Each N-item needs tests for the happy path, 404s and permissions. N5 also needs `stale_reason` checked for every stale trigger: evidence, DQ, canvas, approval, rematerialisation and defer.

**`demo_prepare.py`** (deterministic and idempotent; uses the real API through FastAPI's `TestClient`, in-process, with the replay client):
- **Calls only API endpoints:** pipeline runs, approvals as the BA persona with the note `demo preparation`, and the pipeline again. It never writes SQL and never calls the DDI or NBE directly.
- **Target state:** AI Coach `challenged`, Community `challenged`, Onboarding gated (insufficient, critical DQ open), Pricing `challenged`. The DDI values come from the pipeline; none are hard-coded.
- **Idempotent:** a second run detects the target stage and makes no writes. Prove it with the audit count and the assessment versions unchanged.
- **Never touches a `decided` or `validated` decision**, and reports it as already advanced.
- **`--reset` reseeds first** (`database.seed.run --reset`) for a clean demo. It prints a one-line state table.

## 4. Frontend (Next.js 16, React 19, TypeScript, App Router)

**Plumbing**
- `next.config` rewrite: `/api/:path*` → `http://127.0.0.1:8000/:path*`. **No CORS change.**
- **`lib/api.ts`:** one typed client.
  - It sends `X-Demo-User` from `localStorage`.
  - It throws `ApiError{status, code, message, detail}`.
  - Response types mirror `backend/app/schemas/responses.py`.
- **`lib/actions.ts`:** pure functions.
  - `nextAction(decision, assessment, reviews, me)`;
  - `statusStrip(...)`, in priority order: decided lock, stale, gated, needs rework, review failed, pending approvals, normal;
  - `can(role, action)`, mirroring `ROLE_ACTIONS`. A Vitest parity test reads `permissions.py` as text.
- **`lib/format.ts`** and **`lib/claims.ts`**: `[[id]]` parsing. Unknown IDs render as plain text.
- **`useResource(fetcher)`** returns `{loading, error, data, reload}`. **After any mutation, reload the decision**, because the lifecycle and stale flag can change on any write.
- **Styling:** CSS modules plus tokens on `:root`, with a light and a dark theme. Status is never conveyed by colour alone: always add text or an icon.

**Routes:** `/` portfolio · `/decisions/new` · `/decisions/[id]?tab=…` · `/briefs/[briefId]`, which is printable with `@media print`.

**Global header:**
- "Decision Debt Radar" and a "Synthetic data" badge;
- a role switcher from `GET /users` showing "Name · role", kept in `localStorage`;
- the permanent text **"Demo identity only: not authentication"**;
- an `llm_mode` chip when the mode is replay.

**Portfolio** (`GET /decisions`): title, scenario, lifecycle label, then exactly one of: "DDI x · Band", **INSUFFICIENT EVIDENCE**, or **Stale**. Then the direction, pending approvals and the due date. It never shows `previous_scored_assessment`.

**Workspace**
- **Sticky header:**
  - title, the hypothesis on one line, owner and team;
  - a six-stage stepper with the API's `lifecycle_label`;
  - the status strip;
  - **one** next-action button. If the role can't perform it, the button is disabled and names the roles that can.
- **Tabs:** Overview · Canvas · Evidence · Assessment · Review · Traceability · Brief & Record · Audit.
- **Drawers** (linked by `&item=`): evidence, analysis, claim, finding.

**Copy that must appear verbatim**

| Where | Text |
|---|---|
| Stale banner | "Stale: this assessment no longer reflects the current evidence." + reason + time + "Re-run assessment" |
| DDI card | "Higher = more evidence debt (weaker support). Not a probability the decision is wrong." |
| Direction card | "Direction is separate from DDI." |
| Customer card | "Set by taxonomy, not by AI" |
| Synthesis header | "AI-generated interpretation · validated by code checks · version N" (+ "Replayed demo fixture, not live model output" when not live) |
| Reviewer | "Verdict derived by code from finding severities." |
| Review failed | "No automated adversarial review" |
| Validated badge | "Assessment validated by review", with "The evidence assessment passed review. This does not mean the decision is correct." |
| Validate checkbox | "I understand this validates the evidence assessment, not the decision." |
| Decided | "Decision recorded. Writes are frozen." |
| Defer warning | Defer returns the decision to evidence gathering and makes the assessment stale |
| Approve/reject warning | Approval changes the evidence: the current assessment becomes stale. Rejection is permanent for this item. |

**Tab contents.** Detail is in the Day-6 design review (§E–§L) and the PO's Day-6 implementation prompt §6–§22, both of which this brief adopts.

- **Overview:** the DDI or gate card, the direction card, the top 3 NBE actions, the review verdict, the top supporting and contradicting items, and the decision record.
- **Canvas:** view and edit, with a stale-on-edit confirmation after the first assessment. Read-only once `decided`.
- **Evidence:** four sub-sections.
  - **Register:** history toggle for superseded and rejected items; the drawer from §3/N6.
  - **Customer evidence:** cards, approve and reject with a mandatory note, and below-threshold gap rows.
  - **Data quality:** checks and status updates for analyst and BA.
  - **Analyses:** type, n, effect, CI, parameters and limitations; the experiment status, which shows **"inconclusive" when the CI spans 0**; heterogeneity.
- **Assessment:**
  - the DDI card: score, band, sensitivity, the capped tag, the as-of date and the parameter versions;
  - **"Why this score?":** D1–D7 (score, weight, contribution, observed or defaulted inputs, explanation), then support, × penalty multiplier (P1 and P2 with their inputs and floor), then uncapped, cap, displayed, band, **from stored values only**;
  - the direction card: label, supporting and contradicting shares, the number of direction-bearing items and the threshold;
  - the NBE table. **When gated, the reduction column is replaced by "Resolves N blockers".**
  - the version history: "vN, superseded" rows;
  - the **gate card** when insufficient: INSUFFICIENT EVIDENCE, every reason with its code, DQ links, missing types and the unblocking NBE actions.
- **Review:**
  - the synthesis sections with claim chips, the gaps, and the criteria assessment;
  - the validator report (dropped claims and reasons) in a disclosure;
  - findings grouped Blocking, Warning, Info, each tagged Reviewer or Automated check;
  - for `needs_rework`: Re-synthesise (pm, ba) and Human override (with a mandatory reason, through `POST /assessments/{id}/reviews`);
  - the validate dialog.
- **Traceability:** the matrix from N4. Claim → evidence, and the reverse filter evidence → claims. Gap rows, the evidence status (superseded shown), stance, confidence and source.
- **Brief & Record:**
  - create a Decision Brief (validated or decided only) or a Gated Evidence Summary (insufficient only);
  - show a server 409 as an explanation;
  - list the briefs (N3);
  - the record form: outcome, rationale, acknowledged risk.
- **Audit:** a timeline with the actor name and role (resolved from `/users`), the event in plain words, the time and the key before/after values. Raw JSON is behind a disclosure.

**Brief page.** Render from `content` JSON only, in this order:
1. header (label, synthetic notice, versions and hashes);
2. decision;
3. what the evidence says;
4. supporting and contradicting evidence;
5. uncertainty and gaps;
6. DDI and direction, **or** the gate reasons;
7. DQ and heterogeneity;
8. NBE;
9. review;
10. what would change the conclusion (criteria);
11. decision record;
12. traceability appendix.

**No recommendation section.** For a gated summary, the label appears at the top and bottom. Markdown is a download link only.

**Pipeline progress.** `POST /decisions/{id}/pipeline-runs` is synchronous, so show a blocking progress panel and then the per-stage results the response returns. No polling and no workers.

**Errors**
- **401/403:** show the server message and the allowed roles from `detail`.
- **404:** a not-found page with a back link.
- **409:** the server message, then reload the decision.
- **422:** show the error next to the form field.
- **5xx:** a generic message and Retry. Never a stack trace.
- **Loading, empty, gated, stale, partial assessment and no assessment yet:** each major panel has an explicit state for each.

## 5. Tests

**Backend** (pytest):
- N1–N6 (happy path, 404, permissions);
- the N5 stale reason for each trigger;
- N4 rows equal the view, including gap rows;
- replay provenance end to end on AI Coach, with `fixture_missing` giving a recorded failure;
- `demo_prepare` reaches the target state and a second run makes no writes (audit count and versions unchanged).

**Vitest:**
- `nextAction` across every stage and role;
- `statusStrip` priority;
- stale handling (the DDI is greyed out and the banner is present);
- **gated suppression:** render the gate card and gated NBE and assert **no digit** in the DDI and NBE-reduction regions;
- `previous_scored_assessment` never in the headline;
- `[[id]]` parsing, unknown IDs and a `<script>` quote rendered as text;
- the `can()` parity with `permissions.py`;
- a repo grep: no `dangerouslySetInnerHTML` and no Markdown library.

**Playwright:**
- **Setup:** `demo_prepare.py --reset`, then start the backend (uvicorn, replay mode) and `next start` via `webServer`.
- **The four scenarios:**
  - **AI Coach:** the full path to `decided`, after which write controls are disabled.
  - **Community:** the heterogeneity element and the contradicting `notifications_unwanted` theme are visible; review and validation work.
  - **Onboarding:** **no DDI number anywhere in the DOM** (regex over the page text for a DDI value pattern near DDI labels, plus no `[data-ddi-value]`); the Decision Brief action shows the 409 reason; the Gated Evidence Summary opens with its label.
  - **Pricing:** the CI spans zero, "inconclusive" is visible, and the blocking "no harm" finding is visible.
- **Role checks:** a product analyst sees Validate disabled (and a forced call returns 403); the PM can't approve customer evidence; an executive can record the decision.

## 6. Acceptance gate and final verification

Run, in order:
1. A clean rebuild: `downgrade base`, `upgrade head`, `seed.run --regenerate`, manifest 33/33.
2. The full pytest suite.
3. `demo_prepare` twice, proving idempotency.
4. Vitest.
5. `tsc --noEmit`.
6. `next build`.
7. Playwright.
8. `git diff --stat cef7a05` over the frozen paths (§0): empty.

Then write `docs/day-6-implementation-notes.md` with sections A–K:
- A. implemented;
- B. endpoints;
- C. replay architecture;
- D. frontend architecture;
- E. scenario results (actual DDI and band from the engine);
- F. test counts;
- G. security and trust checks;
- H. clean rebuild;
- I. the frozen-path diff;
- J. known limitations;
- K. Day-7 recommendations.

Also update the README Status and the PRD amendment (D6-03).

**Implementation order:**
1. N1–N6 and tests;
2. replay;
3. `demo_prepare`;
4. proxy;
5. API client and errors;
6. header, role switcher and tokens;
7. portfolio;
8. workspace shell;
9. canvas;
10. evidence, DQ, analyses and customer;
11. assessment;
12. review and validation;
13. traceability;
14. brief and record;
15. audit;
16. Playwright;
17. regression;
18. docs.

**Cut order if behind:** audit polish, then traceability reverse filter, then version diff detail, then the `/decisions/new` form. The four scenario journeys and every D6-05 trust rule are **never** cut.
