# Day 4.1 Remediation Brief (approved by the Product Owner)

**Status:** APPROVED. The Product Owner (PO) text in Part A is binding. Part B records two clarifications made by Opus where the PO text, taken literally, conflicts with the existing guards or with the approved option. Follow Part B exactly.
**Baseline:** working tree on top of `f6209e9`, Alembic head `0005`, 476 tests passing, manifest 33/33. Nothing is committed.

## Part A: Product Owner remediation (binding)

Resolve exactly two findings from the independent Day-4 review.
- Do not start Day 5, redesign the architecture or make speculative improvements.
- Do not change DDI v0.1: no change to any DDI formula, dimension, penalty, gating rule, direction rule, sensitivity rule or DDI parameter.
- Do not change NBE v0.1 files in place. The NBE change is versioned as NBE v0.2.

### Remediation 1: NBE v0.2 blocker dependency

**Problem.** In the insufficient-evidence state, NBE ranks `extend_observation_or_refresh_data` above `fix_dq_or_instrumentation`, even when an `open_critical_dq` issue affects the success metric. Extending observation cannot supply usable success-metric evidence while that defect blocks the metric.

**Rule.** It must be generic and configuration-driven, not hard-coded for Onboarding.
- When an `open_critical_dq` blocker affects the decision's success metric, an action may not claim `success_metric_evidence` as a resolved blocker unless that action itself resolves the blocking DQ issue.
- Actions such as extending observation or refreshing data, customer interviews, surveys and replication cannot claim it.
- `fix_dq_or_instrumentation` may resolve the DQ blocker.
- Do not hard-code fix-DQ to rank first. The ranking must emerge from the dependency model.

**Preserve:**
- effort bands and their day values;
- the priority formula `priority = relevance * potential_ddi_reduction / effort_days`, using explicit names;
- tie-breaking;
- the meaning of `expected_reduction`;
- relevance values;
- the action catalogue, except where required to represent the dependency;
- the DDI methodology and parameters.

**Versioning.**
- Create `nbe_params_v0.2` with its own SHA-256 hash and an explicit reference to the active DDI parameter version.
- Validate it with the existing loader, which must fail on a hash or version mismatch, and register it in the parameter registry.
- Do not overwrite v0.1.
- Document exactly what changed between v0.1 and v0.2.

**Tests:**
1. The current Onboarding insufficient-evidence state no longer ranks `extend_observation_or_refresh_data` ahead of `fix_dq_or_instrumentation` merely because extending observation claims more blockers.
2. While an `open_critical_dq` issue affects the success metric, `extend_observation_or_refresh_data` and the other evidence-gathering actions cannot claim `success_metric_evidence` unless they resolve the dependency.
3. `fix_dq_or_instrumentation` can resolve the relevant DQ blocker.
4. Once the DQ dependency is removed, previously blocked actions can claim `success_metric_evidence` again.
5. The generic rule works beyond the Onboarding fixture.
6. NBE v0.1 behaviour is unchanged when explicitly evaluated under v0.1.
7. The v0.2 hash is deterministic and validated.
8. Existing Day-3 NBE tests keep passing unless they are intentionally versioned to v0.2 behaviour. Document every changed test and why. Do not weaken tests.

### Remediation 2: descriptive evidence must not dilute D6

**Problem.** Trend and funnel evidence is linked to the success metric but has no effect size. It therefore enters D6 (Behavioural Evidence Strength, which ignores stance) with a materiality of 0, and lowers D6.

**Decision (option a).** Descriptive trend and funnel evidence remain valid evidence but do not count toward D6. Do not:
- change the D6 formula;
- add a dimension;
- remove trend or funnel evidence;
- remove it from traceability, evidence synthesis, the Reviewer/Critic or decision-brief inputs.

**Required behaviour.** Trend and funnel evidence (effect NULL) do not count toward D6. Quantified behavioural evidence (effect present) still counts under the existing D6 rules.

**Tests:**
1. A trend item with no effect does not contribute to D6.
2. A funnel item with no effect does not contribute to D6.
3. Removing a descriptive item does not change D6 when nothing else changes.
4. Adding descriptive evidence cannot reduce D6.
5. Quantified behavioural evidence affects D6 exactly as before.
6. Flipping a quantified behavioural item's stance leaves D6 unchanged.
7. Descriptive evidence stays available to evidence-synthesis inputs, the traceability matrix, Reviewer/Critic inputs and decision-brief inputs, meaning it remains an active evidence row with its analysis link.

### Documentation, scope, acceptance and report

**Documentation.** Update only where these two changes require it:
- `docs/DDI-spec.md` and `docs/NBE-spec.md`;
- `docs/day-4-implementation-notes.md`;
- PRD or traceability text that becomes inaccurate;
- the analytics docs;
- `tests/README.md`.

The documentation must state clearly:
- NBE v0.1 is the original methodology.
- NBE v0.2 adds the success-metric blocker dependency under an open critical DQ issue.
- Descriptive trend and funnel evidence remains valid evidence but does not count toward D6, because it has no quantitative effect size.

**Must not:**
- start Day 5;
- add customer evidence, LLM synthesis, the Reviewer, brief generation or agents;
- change DDI v0.1 or its parameters;
- change the P1, P2, direction or sensitivity methodology;
- change the DQ, heterogeneity, experiment or evidence identity/supersession methodology, except the identity note in B2;
- introduce LLM-generated SQL or unrestricted segment scanning;
- make unrelated refactors.

Document any other issue instead of fixing it.

**Regression checks:**
- clean rebuild: downgrade base, upgrade head, regenerate and seed, validate the manifest;
- the full pytest suite, including the Day-3 and Day-4 suites and the new tests;
- the scope guard;
- parameter hash validation;
- determinism checks.

**Final report:**
- status: `DAY 4.1 — PASS` or `DAY 4.1 — FAIL`;
- NBE v0.2: files changed, the exact change, the hash, confirmation that v0.1 is preserved, the Onboarding ranking before and after, and the tests;
- D6: files changed, the exact rule, the tests, and proof that descriptive evidence no longer dilutes D6;
- regression counts and results;
- a scope audit;
- remaining issues.

Do not commit or push.

## Part B: Opus clarifications (binding)

### B1. Frozen-path guard (T-GUARD-1)

The PO explicitly authorised an NBE v0.2 methodology change, which needs code in `backend/app/domain/nbe` to read the new dependency configuration. Update T-GUARD-1 so that:
- `backend/app/domain/ddi/**` and `backend/config/ddi/**` still show **no diff** against `f6209e9`. DDI v0.1 stays untouched, which also forces Remediation 2 to be done outside the DDI engine (see B2).
- `backend/config/nbe/nbe_params_v0.1.yaml` shows no diff, so v0.1 is preserved.
- `backend/app/domain/nbe/**` may change, but only to read the v0.2 dependency configuration. Under `nbe_params_v0.1`, the engine's output must match `f6209e9` exactly. A regression test runs the Day-3 NBE fixtures through the engine under v0.1 and compares the results.
- `params_hashes.json` may gain only `analytics_params_v0.1` (Day 4) and `nbe_params_v0.2`.

**Active version.**
- v0.2 becomes the default, in both the `app.core.config` default and `.env.example`.
- v0.2 references `ddi_params_v0.1`.
- Assessments store `nbe_params_v0.2` and its hash.
- v0.1 stays loadable for regression testing.

### B2. How option (a) is implemented

Option (a), as presented in the review, means descriptive items are **not linked to the success metric**. The frozen DDI engine (`scoring.py`) selects D6 items by `metric_id == success_metric_id`, so it then excludes them without any change to DDI code.

- **Materialisation.** In evidence materialisation, trend and funnel evidence get `metric_id = NULL`.
  - The metric they describe stays traceable through `analysis_id`, because the analysis row records the metric in `params` and `result`.
  - The evidence summary names the metric.
- **No DDI code changes.** Do not change `backend/app/domain/ddi/**` (see B1).
- **Identity.** The `analysis_identity` of descriptive evidence must keep using the analysed metric taken from the analysis, not `evidence.metric_id`. That way identities don't change for this reason.
- **Known consequence.** Report it explicitly; do not work around it.
  - Descriptive evidence no longer counts as "evidence directly linked to the success metric" for the DDI gate.
  - For Onboarding after accepting DEF-ONB-002, the gate reasons are expected to gain `success_metric_evidence`, because only trend and funnel evidence exist there.
  - Report the gate reasons before and after for all four scenarios.
- **Remediation 2, test 7** is satisfied by showing that descriptive rows:
  - are active evidence with an `analysis_id`;
  - appear in `v_traceability_matrix`;
  - are present in the evidence set the Day-5 stages will read, meaning the evidence list endpoint and the facts items.
