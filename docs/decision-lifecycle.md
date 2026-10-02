# Decision Lifecycle Specification

**Status:** v0.1, implemented on Day 3 (see section 8). Parent: [PRD-v0.1.md](PRD-v0.1.md) §23.
**Scope rule:** the MVP implements the lifecycle **only through "Human Decision Recorded"**. Outcome tracking is future scope.

> DDI is a proposed portfolio-project framework (a transparent evidence-risk heuristic), not an industry standard. All FitConnect data is synthetic.

## 1. Stages

| # | Stage (display) | `lifecycle_stage` value | Purpose | MVP |
|---|---|---|---|---|
| 1 | Decision Created | `created` | Canvas completed: what, hypothesis, success metric, deadline, risk, what would change our mind | Yes |
| 2 | Evidence Gathered | `evidence_gathered` | Evidence and data sources linked and inspectable | Yes |
| 3 | Assessment Run | `assessed` | Seven-stage pipeline complete: DDI or INSUFFICIENT EVIDENCE, claims, matrix, NBE | Yes |
| 4 | Evidence Challenged | `challenged` | Reviewer/Critic has run. Challenges and verdict stored | Yes |
| 5 | Decision Validated | `validated` | The **assessment** passed adversarial review (or was human-overridden with reason). *Not* a statement that the decision is correct | Yes |
| 6 | Human Decision Recorded | `decided` | Human outcome (approve / reject / defer / approve-with-conditions), rationale, risk acknowledgement | Yes (final MVP stage) |
| 7 | Outcome Observed | (future) | Record actual results and attribute them | **No** |
| 8 | Re-assessment | (future) | Outcome-informed revisit of evidence standards and the decision | **No** |

## 2. Why it matters (vision)
The eventual product is not a one-time evidence check. With outcome tracking it could learn whether evidence-backed decisions produced better outcomes and which evidence gaps matter most. The MVP builds stages 1–6 and stores enough (versioned assessments, parameter version, evidence links, decision record) that stages 7–8 can be added later without re-modelling. No outcome tables, fields, screens or placeholders ship in the MVP.

## 3. State diagram (MVP)

```
created ──► evidence_gathered ──► assessed ──► challenged ──► validated ──► decided (terminal in MVP)
               ▲                     │  │            │
               │   stale: evidence    │  │ partial    │ needs_rework (not overridden)
               └───── added / canvas ─┘  └─ stays at  └─ stays at challenged until re-run or override
                      edited               evidence_gathered
validated ──(human records "defer")──► evidence_gathered (deferral record kept in history)
```

## 4. Transition table

| From → To | Trigger | Guard (must be true) | Allowed personas | Audit event |
|---|---|---|---|---|
| (none) → `created` | Save canvas | Canvas valid (CV-1…CV-6) | PM, BA | `decision.created` |
| `created` → `evidence_gathered` | "Confirm evidence base" | Success metric has linked data source **or** ≥1 evidence item linked | PM, BA, Product Analyst | `decision.evidence_gathered` |
| `evidence_gathered` → `assessed` | Assessment completes | Assessment state is `scored` or `insufficient_evidence` (not `partial`). Canvas locked at start | PM, BA, Product Analyst | `assessment.completed` |
| `assessed` → `challenged` | A review is recorded (Day 3: human review; Day 5: Reviewer agent) | A verdict is stored for the current assessment | PM, BA, Department Leader, Executive (human review) | `review.completed` |
| `challenged` → `validated` | Verdict `ready`, or override | Verdict `ready`; or `needs_rework` plus human override with reason (BR-13) | PM, BA, Department Leader, Executive | `assessment.validated` / `assessment.override` |
| `validated` → `decided` | Record decision | Rationale present. If band High/Critical or state INSUFFICIENT: acknowledgement checked (BR-11) | Decision owner, Department Leader (own department), Executive | `decision.recorded` |
| `assessed`/`challenged`/`validated` → `evidence_gathered` | Evidence added, evidence changed, canvas edited | Marks `assessment_stale = true` | PM, BA, Product Analyst | `assessment.stale` |
| `validated` → `evidence_gathered` | Human records outcome `defer` | The deferral record (with rationale) is kept. The decision never enters `decided`. A new assessment version is required before deciding again | Executive, Department Leader, decision owner | `decision.deferred` |

Skipping a stage, or a persona acting outside its permissions, is rejected with an explanation and logged as `transition.rejected`.

## 5. Rules
- LC-1 `lifecycle_stage` changes only through the transition service. Direct updates are not exposed.
- LC-2 Every transition writes an `audit_logs` row (actor, from, to, timestamp, reason).
- LC-3 A `decided` decision and its decision record are immutable in the MVP. (`defer` outcomes do not produce `decided`; they are historical records and the decision returns to `evidence_gathered`.) Corrections are future scope.
- LC-4 Re-running an assessment before a decision creates a new version (`decision_assessments.version`). The previous versions become superseded (any version lower than the latest; derived, not stored). It re-runs from the Assessment stage. This is **not** the future "Re-assessment" stage.
- LC-5 `partial` assessments (a failed stage or timeout) never advance the lifecycle.
- LC-6 "Validated" wording in the UI must say "Assessment validated by review" and never imply decision correctness.

## 6. Acceptance criteria (MVP transitions)
Canonical list: PRD §23.4 (AC-19 to AC-24). Additional detail:

| ID | Criterion |
|---|---|
| LC-AC-1 | Every transition in section 4 has a test for the success path and for each guard failure. |
| LC-AC-2 | An attempted skipped transition (for example `created` → `decided`) returns a rejection with the missing stage and writes `transition.rejected`. |
| LC-AC-3 | Adding an evidence item to an `assessed` decision sets `assessment_stale` and returns it to `evidence_gathered`. |
| LC-AC-4 | Recording `defer` on a `validated` decision stores the record, returns the decision to `evidence_gathered` and never sets `decided`. |
| LC-AC-5 | No outcome-related column, table, endpoint or UI element exists in the MVP. |

## 7. Future (not MVP, no implementation)
Outcome Observed (outcome definition, measurement window, attribution caveats) and outcome-informed Re-assessment. Related future analytics: PRD §29.

## 8. Day-3 implementation (services, database, API)

**Names.** The stage values are the database enum values (`created`, `evidence_gathered`, `assessed`, `challenged`, `validated`, `decided`). API responses return `lifecycle_stage` and a display label. The label for `validated` is exactly **"Assessment validated by review"** (LC-6).

**Service rules.**
- An assessment may run only from `evidence_gathered`. A `partial` assessment never advances the stage. The highest assessment version is current, including a partial one; the previous scored version is exposed separately as historical.
- Adding or changing evidence, editing the canvas after the lock, or changing the status of a data-quality check, when the stage is `assessed`, `challenged` or `validated`, sets `assessment_stale = true` and returns the stage to `evidence_gathered` (audit: the change itself, then `assessment.stale`).
- A human review is recorded on the current, non-partial assessment while the stage is `assessed` or `challenged`. The first review moves `assessed` to `challenged`.
- `validate` (`challenged` to `validated`) requires the latest review verdict `ready`. If any review of the assessment was `needs_rework`, validation additionally requires that the latest review is a human review with a non-empty reason (the override, BR-13). The audit event is then `assessment.override` instead of `assessment.validated`. A human `needs_rework` verdict must itself carry a reason.
- Recording a decision requires `validated`. BR-11: a non-scored assessment or a High/Critical band needs `acknowledged_risk` (service: 422; database trigger as backstop). `defer` stores the record, returns the stage to `evidence_gathered` (stale) in the same transaction and never sets `decided`. Any other outcome stores the single final record and sets `decided`, after which every write to the decision's records is rejected.
- `decision_due_date` must be on or after today at creation, using the injected clock.

**Permissions (role switcher, demo identity only).** The header `X-Demo-User: <seeded user id>` selects the user; the server reads role and team from the database. Missing or unknown user: 401. Not permitted: 403. Create/edit canvas: PM, BA. Confirm evidence base, add evidence, run assessment: PM, BA, Product Analyst. Human review: PM, BA, Department Leader, Executive. Validate: PM, BA, Department Leader (own team), Executive. Record decision: the decision owner (any role), Department Leader (own team), Executive. Update DQ check status: Product Analyst, BA. Recommendation status: PM, BA, Product Analyst. Read: everyone. "Own team" means `user.team_id = decision.team_id`.

**Audit.** Every event writes exactly one `audit_logs` row in the same transaction, with `actor_id` the demo user: `decision.created`, `canvas.edited`, `decision.evidence_gathered`, `evidence.added`, `evidence.updated`, `assessment.completed`, `review.completed`, `assessment.validated`, `assessment.override`, `decision.recorded`, `decision.deferred`, `recommendation.status_changed`, `dq_check.status_changed` and `assessment.stale` (for the stale transition). A rejected transition or a refused persona is rolled back and then logged as `transition.rejected` in its own small transaction (LC-AC-2).

**Database backstop.** `ddr_decision_lifecycle_guard` rejects illegal pairs, requires a locked canvas and a completed assessment row to enter `assessed`, requires `assessment_stale` when returning to `evidence_gathered`, applies the canvas-edit rule and makes `decided` immutable. See ERD section 5.
