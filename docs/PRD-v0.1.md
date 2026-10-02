# Decision Debt Radar: Product Requirements Document v0.1

**Status:** v0.1 revision 2 (product direction approved. Refinements in sections 23–30 awaiting Product Owner approval). No implementation (database, backend, frontend, agents, infrastructure) begins until the Product Owner says: **"Approved. Start Day 1 implementation."**
**Owner:** Product Owner. **Prepared by:** Architecture partner (Claude).

**Revision 2 changes:** added Decision Lifecycle (§23), Evidence Health (§24), DDI transparency UX (§25), Decision Canvas (§26), DDI positioning and limitations (§27), Portfolio Demonstration Narrative (§28), Future Product Analytics (§29) and scope control (§30). Updated FR, MVP requirements, data model, acceptance criteria and out-of-scope. The DDI mathematics, the four-agent architecture and the seven-stage pipeline are unchanged.

**Supporting Day-1 specifications** (canonical detail lives there. This PRD summarizes and references): [DDI-spec.md](DDI-spec.md) · [traceability-spec.md](traceability-spec.md) · [NBE-spec.md](NBE-spec.md) · [ERD.md](ERD.md) · [decision-lifecycle.md](decision-lifecycle.md) · [decision-canvas.md](decision-canvas.md) · [ADRs.md](ADRs.md)
**Tagline:** Agentic Decision Intelligence for Evidence-Based Organizations.

> **Framework disclaimer.** "Decision Debt" and the "Decision Debt Index (DDI)" are a **proposed framework created for this portfolio project**. They are not an established industry standard or validated metric. Weights and parameters are transparent assumptions, not empirically calibrated values.
>
> **What DDI is, and is not.** DDI is **a transparent evidence-risk heuristic for business decisions.** It is *not* an objective measure of decision quality, a scientifically validated universal score, an industry standard, or a predictor of business outcomes. See §27.
>
> **Data disclaimer.** All FitConnect data is **synthetic**. FitConnect is a fictional company. Synthetic data is labelled as such in the database, the UI, exports, the Power BI report and the README. It is never presented as real-world data.

---

## 1. Final Product Vision

Decision Debt Radar (DDR) is a horizontal B2B decision-intelligence platform that tells an organization **how well an important decision is supported by evidence**. It does not tell the organization what to decide.

For each registered decision DDR:

1. Collects and grades linked evidence (behavioral, experimental, customer, financial, anecdotal).
2. Assesses data quality before trusting any analysis.
3. Runs validated quantitative analyses.
4. Synthesizes what supports, contradicts and is missing.
5. Computes a **deterministic, auditable DDI** (or declares **INSUFFICIENT EVIDENCE**).
6. Subjects the conclusion to adversarial review.
7. Ranks **Next Best Evidence** actions.
8. Generates a decision brief.
9. Records a **human** decision with rationale.

Every conclusion is traceable to its evidence through the **Evidence Traceability Matrix**. The platform core is industry-agnostic. FitConnect (a fictional fitness/wellness company) is only the first demo tenant.

**Design principles**

| # | Principle |
|---|---|
| P1 | Humans decide. DDR informs. |
| P2 | The LLM classifies, summarizes and explains. **Code computes the numbers.** |
| P3 | No claim without a valid evidence ID. |
| P4 | "Insufficient evidence" is a first-class, honest outcome. |
| P5 | Every score is explainable down to inputs and parameters. |
| P6 | Synthetic data is always labelled. Never fabricate evidence. |
| P7 | Simplest architecture that can be finished and demonstrated in one week. |

**Central product message:** *"Decision Debt Radar does not decide for you. It tells you how well your decision is supported, what could invalidate your reasoning, and what evidence you should gather next."*

## 2. Product Positioning

- **Category:** Decision-intelligence / evidence-governance layer (it sits beside BI, experimentation and research tools, not in place of them).
- **Analogy:** "Technical debt tracks shortcuts in code. Decision debt tracks shortcuts in evidence."
- **Not:** an auto-decision engine, a BI dashboard, an experimentation platform, an "AI chatbot", an "AI dashboard" or a generic "AI analytics tool". The agents are an implementation mechanism for a decision-governance workflow, not the product's identity.
- **Differentiators:** (1) a score that is deterministic and decomposable, (2) mandatory adversarial review, (3) Next Best Evidence prioritization, (4) end-to-end traceability, (5) honest refusal when evidence is insufficient.
- **Portfolio positioning:** demonstrates BA rigor (requirements, traceability, business rules), PM craft (personas, JTBD, prioritization, experimentation), analytics (SQL, DQ, statistics, Power BI) and AI engineering (tool use, structured output, evaluation, HITL).

## 3. Personas

| Persona | Goals | Problems | Key workflows | Required information | Permissions (role-switcher) | Expected outputs |
|---|---|---|---|---|---|---|
| **Product Manager** (primary) | Ship the right bets and defend them | Evidence scattered, pressure to decide fast, unclear what to validate | Register decision → attach evidence → run assessment → act on Next Best Evidence | DDI, supports/contradicts/gaps, next actions | Create/edit own decisions, run assessments, record decision for own decisions | Decision brief, hypothesis, experiment plan, PRD-lite |
| **Business Analyst** | Traceable, well-sourced requirements | Unsourced stakeholder claims, no audit trail | Curate evidence and sources, maintain the traceability matrix, resolve DQ flags | Evidence register, source reliability, traceability matrix | Edit evidence, sources, metrics definitions; run assessments | Traceability matrix, evidence register |
| **Product Analyst** | Rigorous quantitative evidence | Rebuilding the same analysis, hidden DQ problems, p-hacking | Run and review analyses, approve metric definitions, review experiment readouts | DQ report, analysis outputs with limitations, experiment results | Run analytics, publish observations and experiment results | Analysis notes, experiment readouts |
| **Strategy / BizOps Manager** | Allocate validation effort across initiatives | No portfolio view of decision risk | Review Debt Radar, compare decisions, prioritize investigations | Portfolio DDI, debt by team/type, aging | Read all, assign reviewers, view portfolio | Portfolio report, Power BI dashboard |
| **Department Leader** | Fund initiatives with eyes open | Cannot tell if the proposal is evidence-backed | Review briefs for own department, approve/reject | One-page brief, DDI band, key gaps | Read and comment, approve in-department decisions | Approval record |
| **Executive / Decision Maker** | Decide with known confidence | Too much detail, no confidence signal | Read brief, record final decision | Brief, Reviewer challenges, Next Best Evidence | Read all, record final decision | Decision record with rationale |

## 4. Jobs-to-be-Done

| Persona | JTBD |
|---|---|
| PM | When I propose a bet, I want to know how well it is supported, so I can defend it or de-risk it. |
| BA | When stakeholders cite "evidence", I want it sourced, graded and linked to requirements, so the rationale is traceable. |
| Product Analyst | When asked "does the data support this?", I want consistent, quality-checked analyses with stated limitations, so I don't rebuild the work or mislead. |
| BizOps | When many initiatives compete, I want to see which rest on weak evidence, so I can direct validation effort. |
| Dept Leader | When I approve spend, I want to know what is missing, so I don't fund guesses. |
| Executive | When I decide, I want a one-page brief that states confidence and challenges, so I own the decision knowingly. |

## 5. User Journeys

**J1: Assess a decision (PM, primary).**
1. PM registers a decision (title, description, hypothesis, success metric, decision type, risk level).
2. PM attaches or confirms linked evidence/sources.
3. PM clicks **Run Assessment**. The UI shows the 7-stage pipeline (section 15) progressing.
4. PM reviews each stage: DQ report, quantitative analysis, customer evidence, experiment evidence, synthesis, adversarial review.
5. PM sees the DDI, or **INSUFFICIENT EVIDENCE** with the reason.
6. PM reviews the Next Best Evidence ranking and accepts or rejects actions.
7. PM generates the decision brief.

**J2: Trace a claim (BA).** Open a claim in the brief → see Evidence → Source → Analysis → Conclusion in the matrix → export the matrix.

**J3: Portfolio triage (BizOps).** Open the Debt Radar → filter by team/type/band → open the highest-debt decision → assign a reviewer.

**J4: Decide (Executive).** Open the brief → read supports/contradicts/gaps and Reviewer challenges → record decision (approve / reject / defer / approve with conditions) with rationale. If the DDI band is High/Critical or the state is INSUFFICIENT EVIDENCE, an explicit acknowledgement is required.

**J5: Resolve a data-quality block (Product Analyst).** DQ stage fails on a critical check → analyst reviews findings → marks the issue resolved or documents an accepted limitation → re-runs the assessment.

## 6. MVP Requirements (summary)

| ID | Requirement | Priority |
|---|---|---|
| M1 | Decision registry with hypothesis, success metric, type, status | Must |
| M2 | Evidence register with sources, stance, type, grade, period | Must |
| M3 | Seven-stage pipeline visible in the UI | Must |
| M4 | Data quality assessment gating downstream analysis | Must |
| M5 | Six analytics capabilities (section 16) | Must |
| M6 | Customer evidence (theme extraction) and experiment evidence capabilities | Must |
| M7 | Evidence synthesis with claims, each citing valid evidence IDs | Must |
| M8 | Deterministic DDI + sensitivity analysis + INSUFFICIENT EVIDENCE state | Must |
| M9 | Adversarial Reviewer with structured challenges | Must |
| M10 | Evidence Traceability Matrix (view + export) | Must |
| M11 | Next Best Evidence ranking | Must |
| M12 | Decision brief generation | Must |
| M13 | Human decision record with rationale, role-switcher | Must |
| M14 | Audit log and agent-run log | Must |
| M15 | Four seeded FitConnect scenarios (synthetic, labelled) | Must |
| M16 | Evaluation harness | Must |
| M17 | Power BI dashboard on reporting views | **Must (PO-required)** |
| M18 | Experiment plan / PRD-lite generation | Should |
| M19 | Anomaly flag (simple z-score) | Could |
| M20 | Hosted public demo | Could (only after core is stable) |
| M21 | Decision Lifecycle implemented through "Human Decision Recorded" (no outcome tracking) | Must |
| M22 | Decision Canvas (lightweight form on the decision object) | Must |
| M23 | Evidence Health view in the reporting layer + Power BI page | Must (view and Power BI). In-app summary table is Should |
| M24 | Transparent DDI panel (breakdown, penalties, parameters, sensitivity, drivers, NBE) | Must |

## 7. Functional Requirements

**Decision management**
- FR-1 Create/edit/list decisions with lifecycle stage (§23): `created → evidence_gathered → assessed → challenged → validated → decided`.
- FR-2 Each decision stores hypothesis, success metric (FK to metrics), decision type, risk level, owner.
- FR-3 Role-switcher selects persona. Permissions enforced server-side from a role header (demo only, no authentication).

**Evidence**
- FR-4 CSV ingestion of data sources (users, events, subscriptions, tickets, survey/reviews, experiments) with schema validation and `is_synthetic` flag.
- FR-5 Evidence items have type, stance (supports/contradicts/neutral), strength grade (A–D), observed period, source, and optional links to metric/experiment/insight/analysis.
- FR-6 Evidence sources carry a reliability tier (1 to 4) with documented rationale.

**Pipeline**
- FR-7 Stage 1 Data Quality: completeness, duplicates, referential integrity, event-sequence sanity, volume anomalies, tracking gaps. Output: pass / warn / critical per check.
- FR-8 Stage 2 Quantitative Analysis: trend, segmentation, funnel, retention. Every result includes query, n, limitations.
- FR-9 Stage 3 Customer Evidence: theme and sentiment extraction from feedback/tickets with quote counts and sampled quotes.
- FR-10 Stage 4 Experiment Evidence: SRM check, effect size, CI, power, design rank.
- FR-11 Stage 5 Evidence Synthesis: structured claims, each with ≥1 evidence ID, stance and confidence. Gaps listed explicitly.
- FR-12 Stage 6 Adversarial Review: structured challenges (type, severity, target claim/evidence), verdict.
- FR-13 Stage 7 Decision Brief: one-page brief + exportable.
- FR-14 Each stage is individually inspectable (status, outputs, inputs, duration, model, prompt version).

**DDI**
- FR-15 DDI is computed by a pure-code engine from structured evidence attributes.
- FR-16 DDI breakdown by dimension, parameters version and sensitivity table is shown.
- FR-17 INSUFFICIENT EVIDENCE state per business rules BR-1 to BR-4. No score displayed.

**Traceability and Next Best Evidence**
- FR-18 Traceability matrix view and CSV/Markdown export.
- FR-19 Next Best Evidence list per assessment with effort, expected reduction, relevance, priority.

**Governance**
- FR-20 Human decision record with rationale and acknowledgement of risk.
- FR-21 Immutable audit log for all state changes. Agent-run log for all agent calls.
- FR-22 Reviewer challenges and human responses recorded.

**Lifecycle, Canvas, Evidence Health, DDI transparency (revision 2)**
- FR-23 Decisions move through the MVP lifecycle stages Created → Evidence Gathered → Assessed → Challenged → Validated → Decided, with guarded, audited transitions (§23).
- FR-24 Decision creation uses the Decision Canvas (§26). A decision cannot leave `created` until the canvas passes validation.
- FR-25 An **Evidence Health** reporting view and Power BI page summarize the organization's evidence base descriptively, with no composite score (§24).
- FR-26 The DDI is always displayed through the transparent DDI panel (§25). A bare number is not a valid display.
- FR-27 The Reviewer and Synthesis agents receive the canvas's "what would change our mind" criteria and report whether available evidence meets them.
- FR-28 Edits to the canvas after the first assessment are audit-logged and flagged on the brief.
- FR-29 The UI shows a persistent label: "DDI is an evidence-risk heuristic, not a measure of decision quality."
- FR-30 Re-running an assessment before a human decision creates a new assessment version. Earlier versions become superseded: "superseded" means any version lower than the decision's latest version. It is derived, not stored.

## 8. Non-Functional Requirements

| ID | Requirement |
|---|---|
| NFR-1 | **Reliability:** pipeline stages are idempotent and re-runnable. A failed stage yields "partial" status, never a silent success. |
| NFR-2 | **Safety:** all generated SQL is parsed, allow-listed to reporting views, read-only, row-limited and time-limited. |
| NFR-3 | **Determinism:** same inputs and parameters → same DDI. DDI engine has no LLM dependency. |
| NFR-4 | **Traceability:** 100% of displayed claims link to evidence IDs (enforced in code). |
| NFR-5 | **Performance:** full assessment ≤ ~3 minutes on a laptop. Page loads < 2 s on seeded data. Analytics run against pre-aggregated views where needed. |
| NFR-6 | **Reproducibility:** `docker compose up` + seed script restores the demo. Data generator uses a fixed random seed. |
| NFR-7 | **Observability:** token, latency and error metrics recorded per agent run. |
| NFR-8 | **Security (demo):** no real authentication. No real personal data. No secrets in the repo. API key via environment variable. |
| NFR-9 | **Maintainability:** typed Python (Pydantic), unit-tested DDI and SQL guard, versioned prompts and DDI parameters. |
| NFR-10 | **Accessibility/UX:** keyboard-navigable, colour is never the only signal for bands, responsive to laptop widths. |
| NFR-11 | **Portability:** industry-agnostic core. FitConnect specifics live only in the `fc_` schema, seed data and scenario configs. |

## 9. Business Rules

| ID | Rule |
|---|---|
| BR-1 | **Insufficient evidence (volume):** DDI is not computed if fewer than 3 evidence items exist or they span fewer than 2 evidence types. |
| BR-2 | **Insufficient evidence (success metric):** DDI is not computed if no evidence relates directly to the decision's success metric. |
| BR-3 | **Insufficient evidence (data quality):** DDI is not computed if an open **critical** DQ failure affects data feeding the success metric. The system states what must be fixed. Day-3 detail: DQ checks of every assessment version of the decision remain relevant. `open` blocks, `accepted` does not block but is shown as a warning, `resolved` does not block. |
| BR-4 | **No forced score:** the UI never shows a numeric DDI, a default, or an estimate when BR-1 to BR-3 trigger. |
| BR-5 | The LLM never sets, adjusts or overrides the DDI. It supplies classifications that are validated against enums and rubrics. |
| BR-6 | Every claim must cite ≥1 existing evidence ID. Uncited claims are discarded and logged. |
| BR-7 | Observational evidence must not be described as causal. Causal language requires an experiment of design rank ≥ holdout with passing SRM check. The Reviewer enforces this. |
| BR-8 | Stale evidence is down-weighted by the freshness half-life per evidence type (parameterized). |
| BR-9 | Contradicting evidence is never hidden. The brief must list it. |
| BR-10 | Only a human can record a decision. Agents may only propose. |
| BR-11 | Deciding while the band is High/Critical or state is INSUFFICIENT requires an acknowledgement and rationale. Enforced in the service (422) and by a database trigger. |
| BR-12 | Synthetic data is labelled in every view and export. The platform must not describe it as real. |
| BR-13 | Reviewer verdict "needs rework" blocks brief finalization until the synthesis is re-run or the human overrides with reason. |
| BR-14 | Every state change writes an audit log row. |
| BR-15 | A segment-level effect that materially diverges from the aggregate must be surfaced (see section 16, heterogeneity / aggregate-masking rule). |

## 10. Evidence Traceability Matrix Specification (BA artifact)

**Purpose:** show, for every conclusion, the chain **Decision → Claim → Evidence → Source → Analysis → Conclusion**, so a reviewer can audit the reasoning end to end.

**Columns**

| Column | Description |
|---|---|
| `decision_id` / `decision_title` | The decision under assessment |
| `claim_id` / `claim_text` | An atomic assertion made in the synthesis (e.g. "AI Coach users retain 12 pp better at D90") |
| `claim_type` | descriptive / associative / causal / financial / customer / risk |
| `stance` | supports / contradicts / neutral (relative to the decision hypothesis) |
| `evidence_id` / `evidence_summary` | The evidence item(s) behind the claim |
| `evidence_type`, `strength_grade` | From the evidence register |
| `source_id` / `source_name` / `reliability_tier` | The origin of the evidence |
| `analysis_id` / `analysis_type` / `query_ref` | The analysis that produced or validated the evidence (nullable for qualitative sources) |
| `dq_status` | DQ outcome for the underlying data |
| `conclusion_id` / `conclusion_text` | The assessment-level conclusion the claim feeds (e.g. a DDI dimension finding) |
| `reviewer_challenge_ids` | Reviewer flags attached to this claim |
| `is_synthetic` | Always shown for demo data |

**Rules**
- TM-1 A claim with no evidence is invalid and not stored in the matrix.
- TM-2 Many-to-many: a claim may cite several evidence items. An evidence item may support several claims.
- TM-3 The matrix is a **database view** (`v_traceability_matrix`) over `claims`, `claim_evidence`, `evidence`, `evidence_sources`, `analysis_results`, `decision_assessments`.
- TM-4 Gap rows: missing required evidence types appear as rows with `evidence_id = NULL`, flagged "GAP".
- TM-5 Exportable as CSV and Markdown. It appears in the decision brief appendix.
- TM-6 Versioned per assessment (an assessment re-run creates new claim rows).

**Acceptance:** every claim in a generated brief resolves to ≥1 evidence ID, one source and (if quantitative) one analysis ID in the matrix.

## 11. Next Best Evidence (NBE) Specification

> **Proposed framework for this portfolio project.** Estimates are heuristic and rule-based, not predictions.

**Purpose:** for each assessed decision, answer "what evidence should we get next to reduce Decision Debt most per unit of effort?"

**Candidate actions (catalog, org-configurable):**
fix a DQ issue · run a holdout/A-B test · run a segment-level analysis · run a customer interview sprint · run a survey · extend the observation period · add a financial model with sensitivity range · replicate with a different data source · instrument missing tracking.

**Scoring**

For each candidate action *a*:

- **Effort E(a)** in person-days from the catalog's band (e.g. S = 1, M = 3, L = 8, XL = 15). It is editable per org.
- **Expected reduction R(a)** ∈ [0, 100]: the deterministic engine recomputes the DDI under the *assumption* that the action yields evidence of its **typical attainable strength** on the dimension(s) it targets (dimension score raised to the action's ceiling, neutral stance so no outcome is presumed). R(a) = DDI_now − DDI_assumed. This measures *potential debt reduction*, not the expected result of the evidence. For INSUFFICIENT EVIDENCE decisions, R(a) is the number of unmet gating rules it resolves (shown as "unblocks scoring").
- **Relevance V(a)** ∈ [0, 1]: rule-based: 1.0 if the action targets the success metric directly or addresses a Reviewer *critical* challenge, 0.7 if it addresses a gap on the decision-type checklist, 0.4 if it addresses a secondary dimension.
- **Priority score** = `V(a) × R(a) / E(a)`. Ties break by lower effort. *(Day-3 implementation names: `relevance * potential_ddi_reduction / effort_days`. R(a) is the potential evidence-strength improvement if the action succeeds as intended, never negative, actions at their ceiling are excluded. For INSUFFICIENT decisions R(a) is stored as 0 and the number of resolved blockers is stored separately in `blockers_resolved`. Reviewer-challenge relevance is deferred to Day 5. See [NBE-spec.md](NBE-spec.md).)*

**Display:** a ranked table comparing effort, expected reduction, relevance, priority, "why this", and the dimension(s) addressed. The human can accept, reject or defer, and the response is recorded.

**Assumptions (documented in-product):**
1. Attainable ceilings per action type are assumptions set in a versioned config.
2. Effort bands are rough and org-specific.
3. R(a) ignores the possibility that new evidence contradicts the decision (this is stated in the UI).
4. Candidate actions come from the catalog. The LLM may *suggest* actions and rationale text, but may not set the numbers.
5. Actions are scored independently (no interaction effects) in the MVP.

**Acceptance:** each assessment shows ≥3 ranked actions (or states none apply), and the top-ranked action, when applied in a seeded scenario, reduces the DDI in the direction the engine predicted.

## 12. Four FitConnect Decision Scenarios (all synthetic)

Shared setup: ~50k synthetic users, up to ~2M events over 12 months, fixed random seed. Each scenario's patterns are deliberately generated and documented in a defect/pattern manifest (`data/`) so evaluation has ground truth.

### Scenario 1: AI Coach investment
- **Decision:** Invest in expanding the AI Coach (dedicated team + inference budget).
- **Hypothesis:** AI Coach increases 90-day retention.
- **Seeded patterns:** AI Coach users show a positive engagement and D90 retention correlation. Customer feedback is positive. Inference cost per active user is high. Adoption is concentrated among pre-existing power users (selection effect). One experiment exists but is weak (small n, imbalanced assignment, short duration, wide CI).
- **Expected system behavior:** DDI moderate-to-high. Reviewer flags causation-from-correlation and selection bias. Segment analysis shows the effect largely vanishes after controlling for prior engagement. Cost evidence is present but is not weighed against the benefit. NBE: properly powered holdout, a power-user-excluded analysis.

### Scenario 2: Onboarding redesign
- **Decision:** Fund a full onboarding redesign.
- **Hypothesis:** Redesign will increase activation.
- **Seeded patterns:** Activation declines over the last N weeks. Onboarding step abandonment appears to rise. Support complaints about onboarding rise. **A deliberate tracking defect** (e.g. a step event stops firing on one platform from a certain date, producing a spurious abandonment spike).
- **Expected system behavior:** Stage 1 DQ detects the tracking gap as **critical** for the success metric. **Outcome: INSUFFICIENT EVIDENCE** (BR-3), no DDI shown. The pipeline states what is blocked and why. NBE: fix instrumentation, backfill or re-measure. After the DQ issue is marked resolved in a variant of the seed, the assessment produces a score.

### Scenario 3: Premium pricing increase
- **Decision:** Raise the premium subscription price.
- **Hypothesis:** Higher price increases revenue without unacceptable churn.
- **Seeded patterns:** Revenue upside in a simple model. Pricing-sensitive feedback in surveys/reviews. Conversion dips and churn upticks in some cohorts. A pricing experiment exists but is **inconclusive** (CI spans zero and meaningful harm, underpowered).
- **Expected system behavior:** DDI high. The Reviewer flags that the experiment is inconclusive and may not be presented as support, and that the financial estimate rests on assumed elasticity. NBE: a larger or longer test, a segmented price-sensitivity analysis, a revenue model with a sensitivity range.

### Scenario 4: Community / challenges investment
- **Decision:** Invest in community challenges.
- **Hypothesis:** Community features improve retention.
- **Seeded patterns:** Strong aggregate retention relationship. **Segment effects differ materially:** strongly positive for one segment, near-zero for a second and negative for a third, while the aggregate is strongly positive because joiners are concentrated in the high-baseline segment (**aggregate-vs-segment heterogeneity / aggregate masking**).
- **Terminology note:** this scenario is related to Simpson-type aggregation risks (an aggregate result that misrepresents what happens within segments), but it does **not** claim to reproduce a textbook Simpson's paradox: the aggregate is positive, and the segment effects are mixed (positive, about zero, negative) rather than all reversed. The MVP requirement is to detect and surface heterogeneity and aggregate masking, not to detect a full sign reversal.
- **Expected system behavior:** The aggregate result looks supportive. The segmentation analysis detects materially divergent segment effects and surfaces that the aggregate conceals important segment differences (BR-15). The Reviewer is flagged and challenges the aggregate claim (aggregate masking). The brief recommends a segment-aware decision. NBE: segment-aware validation (segment-level analysis and a segment-level experiment or targeted rollout test).

**Reference behavior table (for evaluation)**

| Scenario | Expected state | Expected DDI band | Must-have reviewer flags | Must-have NBE |
|---|---|---|---|---|
| 1 AI Coach | Scored | Moderate–High | causation/selection bias, weak experiment, cost not weighed | powered holdout |
| 2 Onboarding | **INSUFFICIENT EVIDENCE** | none | tracking defect, blocked metric | fix instrumentation |
| 3 Pricing | Scored | High | inconclusive experiment, assumed elasticity | larger test / sensitivity |
| 4 Community | Scored | Moderate | aggregate masking (heterogeneous segment effects) | segment-aware validation (segment-level analysis / test) |

Bands are expected ranges, validated by the evaluation harness. They are not absolutes.

## 13. DDI Methodology

> **Proposed framework for this portfolio project. Not an industry standard.**

**13.1 Principles.** Deterministic, rule-based, explainable. DDI ∈ [0, 100], where **higher = more decision debt (less support)**.

**13.2 Inputs.** Structured attributes of evidence items and analyses (type, stance, strength grade, source tier, observed period, n, CI, DQ status, experiment design). The LLM may help populate *classification* fields (stance, type, theme). All fields are validated against enums/rubrics and are visible and editable by humans. Strength grades follow a written rubric (see 13.5) and are partly computed from numeric facts (n, CI, design).

**13.3 Dimensions** (scores ∈ [0, 1], 1 = strong support)

| # | Dimension | Definition | Calculation | Data required | Limitations / possible bias |
|---|---|---|---|---|---|
| D1 | Evidence Quality | Reliability of the evidence base | Mean over items of `tier_factor × grade_factor × dq_factor` (tier 1–4 → 1.0/0.75/0.5/0.25; grade A–D → 1.0/0.75/0.5/0.25; dq pass/warn/critical → 1.0/0.7/0.0) | Evidence, sources, DQ | Tier/grade assignment is subjective. Rubrics reduce but don't remove this. |
| D2 | Evidence Coverage | Presence of evidence types required for this decision type | `types_present ÷ types_required`, from a per-decision-type checklist | Decision type, evidence types | Checklist is a human judgment. Org-configurable. Counts presence, not depth. |
| D3 | Evidence Freshness | Recency relative to a type-specific half-life | Mean of `0.5^(age_days ÷ half_life_type)` | Observation periods | Half-lives are assumptions (e.g. behavioral 90 d, customer 180 d, financial 120 d). Recent ≠ relevant. |
| D4 | Experimental Strength | Causal evidence quality | Best experiment: `design_rank × power_factor × integrity_factor` (RCT 1.0, holdout 0.8, pre/post 0.4, none 0); power from n vs MDE; integrity = SRM pass and CI informativeness. 0 if no experiment. | Experiments, results | Most decisions lack experiments (correctly penalized). Statistical significance ≠ business significance. |
| D5 | Customer Evidence | Voice-of-customer support | Saturating function of (sample size × segment coverage × relevance) mapped to [0,1] | Customer insights | Self-selection, vocal-minority bias. Sentiment ≠ behavior. |
| D6 | Behavioral Evidence Strength | Observed user behavior relevant to the success metric, regardless of whether it supports or contradicts the hypothesis (stance reaches the DDI only through P1) | Effect-size magnitude and sample adequacy on the success metric, capped at 0.6 if only observational (cannot reach 1.0 without causal support) | Metric observations, analyses | Correlation ≠ causation. Selection and survivorship effects. |
| D7 | Financial/Business Evidence | Impact quantified with a sourced estimate | Presence × source tier × sensitivity-range present (e.g. 0.5 base + 0.3 sourced + 0.2 sensitivity) | Financial evidence | Often modelled, not observed. Assumptions dominate. |

*Penalty dimensions* (∈ [0,1], 1 = worst)

| # | Dimension | Definition | Calculation | Limitations |
|---|---|---|---|---|
| P1 | Contradiction | Strength-weighted contradiction among direction-bearing evidence, adjusted for evidence quality | `Σ(w_i for contradicting) ÷ Σ(w_i supporting or contradicting)`, where `w_i = tier × grade × freshness × dq_factor` (Day-3 methodology change: neutral items are excluded and `dq_factor` is included) | Depends on stance labelling (Reviewer audits). The segment-divergence floor of 0.3 (BR-15) applies only when the heterogeneity flag is True |
| P2 | Uncertainty | Wide intervals, small samples, single-source dependence | Mean of the available components among {normalized CI width, small-n flag share, normalized source concentration `(HHI − 1/n) ÷ (1 − 1/n)`} | Needs numeric evidence for CI/n. Otherwise only the concentration part applies. |

**13.4 Aggregation**

```
Support  = Σ_k (w_k × D_k)  over applicable positive dimensions, with w_k = 1/K  (equal prior)
Penalty  = 1 + 0.5 × P1 + 0.25 × P2
DDI      = min(100, 100 × (1 − Support) × Penalty)
```

- K is the number of *applicable* dimensions. A dimension may be marked not-applicable for a decision type (for example Financial for a purely UX tweak). Non-applicable dimensions are excluded and the remaining weights renormalized (documented in the breakdown). This is the only adjustment to the equal prior.
- Penalty coefficients (0.5, 0.25) are assumptions chosen so that contradiction is the more severe penalty. They are shown in the UI and kept in the versioned config `ddi_params_v0.1.yaml`.
- **Bands:** Low < 25, Moderate ≥ 25 and < 50, High ≥ 50 and < 75, Critical ≥ 75 and ≤ 100 (assumed thresholds, configurable). A DDI of exactly 100 is Critical. The DDI is rounded to one decimal first, then banded. If the uncapped value exceeds 100, every contribution is scaled by 100 ÷ uncapped (`cap_applied`). Displayed contributions use largest-remainder allocation and sum exactly to the displayed DDI.
- **Meaning (R1):** DDI measures evidence debt, not the probability that the decision is correct. A separate evidence-direction summary (supporting / contradicting / mixed / uncertain) accompanies every DDI and never modifies it (DDI-spec §14).

**13.5 Grading rubric (A–D)** (summary, full text in `docs/DDI-spec.md` later)
A: large sample / experiment with intact design, reliable source, no open DQ warnings · B: adequate sample, observational, reliable source · C: small sample or unverified source or DQ warnings · D: anecdotal, single quote, unknown provenance.

**13.6 Sensitivity analysis.** Because weights are assumptions, DDR reports how robust the result is:
1. Perturb each weight ×0.5 and ×1.5 (renormalized) and recompute. Report the DDI range and whether the band changes.
2. Perturb the penalty coefficients ±50%.
3. Report **rank stability** across decisions on the portfolio view (e.g. does decision A remain riskier than B under all perturbations?).
4. The brief states "robust" (band unchanged in ≥ 90% of perturbations), "sensitive" otherwise.

**13.7 Insufficient evidence** (BR-1 to BR-4). The DDI engine returns `state = INSUFFICIENT_EVIDENCE`, `score = NULL` and `blocking_reasons[]`.

**13.8 LLM boundary.** The LLM may populate/propose classification fields and explain a computed result in prose. It cannot supply or alter any numeric DDI input except via validated, human-visible fields. The engine ignores any numeric in LLM prose.

**13.9 Known limitations (shown in-product).** No ground-truth calibration. Weights are an assumption. Scores compare decisions within an organization's configuration, not across organizations. The mathematical model is **unchanged in revision 2**. Full parameter tables, worked example and sensitivity algorithm are in [DDI-spec.md](DDI-spec.md). Transparency requirements are in §25 and positioning in §27.

## 14. Data Model

PostgreSQL. UUID primary keys. `created_at`/`updated_at` everywhere. `org_id` on tenant tables. `is_synthetic boolean` on all data-bearing tables. FitConnect raw behavioral data lives in schema `fc_` and is reached only through registered `data_sources`/`metrics` and read-only reporting views. The core never references `fc_` tables.

### 14.1 Core tables

| Table | Purpose | Key fields (type) | PK / FKs / indexes |
|---|---|---|---|
| `organizations` | Tenant | id uuid, name text, industry text, is_synthetic bool | PK id |
| `teams` | Org units | id, org_id, name | PK id; FK org; idx(org_id) |
| `users` | Demo users | id, org_id, team_id, name, email, role enum(pm, ba, product_analyst, bizops, dept_leader, executive) | FK org, team |
| `data_sources` | Origin of datasets | id, org_id, name, source_type enum(csv, survey, ticketing, other), owner_id, refresh_cadence, last_loaded_at, reliability_tier smallint(1–4), tier_rationale text, is_synthetic | FK org, user |
| `metrics` | KPI definitions | id, org_id, name, definition text, sql_logic text, unit, grain, data_source_id, owner_id | unique(org_id,name) |
| `metric_observations` | Time series | id, metric_id, observed_at date, segment_key, segment_value, value numeric, n_sample int | FK metric; idx(metric_id, observed_at) |
| `decisions` | Core object | id, org_id, team_id, title, description, hypothesis, success_metric_id, decision_type text, risk_level enum, lifecycle_stage enum(created, evidence_gathered, assessed, challenged, validated, decided), assessment_stale bool, decision_due_date date, current_evidence_notes text, change_my_mind_criteria jsonb (1–5 strings), canvas_completed_at, canvas_locked_at, owner_id, scenario_key, is_synthetic | FKs; idx(org_id,lifecycle_stage). Canvas fields live on this table (no new entity). See [decision-canvas.md](decision-canvas.md) |
| `decision_records` | Final human decision | id, decision_id, decided_by, outcome enum(approve, reject, defer, approve_conditional), rationale text, acknowledged_risk bool, decided_at | FK decision, user. Partial unique index on decision_id WHERE outcome <> 'defer': at most one final record per decision, while deferral records are kept as history |
| `evidence_sources` | Citable origin | id, org_id, data_source_id null, title, ref, source_type, collected_at, reliability_tier, is_synthetic | FK |
| `evidence` | Atomic evidence item | id, decision_id, evidence_source_id, analysis_id null, evidence_type enum(behavioral, experiment, customer, financial, market, anecdotal), summary text, stance enum, strength_grade enum(A–D), observed_start, observed_end, n_sample int null, effect_size numeric null, ci_low, ci_high, metric_id null, experiment_id null, insight_id null, created_by enum(user, agent), agent_run_id null, is_synthetic | FKs; idx(decision_id) |
| `experiments` | Tests | id, org_id, decision_id, name, hypothesis, design enum(rct, holdout, pre_post, other), start_date, end_date, status, primary_metric_id, planned_sample, mde numeric, source_ref text (reference to the raw experiment data within its data source, for example an experiment key, used by the Experiment Evidence stage to locate assignments and outcomes) | FKs |
| `experiment_results` | Outcomes | id, experiment_id, variant, n int, metric_value, effect_size, ci_low, ci_high, p_value, srm_flag bool, notes | FK; idx(experiment_id) |
| `customer_insights` | Qualitative themes | id, org_id, data_source_id, decision_id null, theme, sentiment enum, segment, quote_count int, sample_quotes jsonb, collected_at | FKs |
| `dq_checks` | DQ results | id, assessment_id, data_source_id, check_type, severity enum(pass, warn, critical), finding text, affects_metric_id null, status enum(open, resolved, accepted), resolved_by null | FKs; idx(assessment_id) |
| `analysis_results` | Reproducible analyses | id, decision_id, agent_run_id, analysis_type enum(trend, segmentation, funnel, retention, experiment, comparison), params jsonb, query_text text, result jsonb, n int, limitations text, dq_status | FK; idx(decision_id) |
| `claims` | Atomic synthesis assertions | id, assessment_id, claim_text, claim_type enum, stance, confidence enum(low, medium, high), conclusion_ref text (the DDI dimension or finding the claim feeds, for the traceability matrix `conclusion_ref` column) | FK |
| `claim_evidence` | Claim ↔ evidence (M:N) | claim_id, evidence_id | PK (claim_id, evidence_id) |
| `decision_assessments` | Versioned DDI snapshots | id, decision_id, version int, state enum(scored, insufficient_evidence, partial), ddi_score numeric null, ddi_band null, dimension_scores jsonb, penalty_scores jsonb, blocking_reasons jsonb, sensitivity jsonb, params_version text, params_hash text, nbe_params_version text, nbe_params_hash text, evidence_fingerprint text, as_of_date date, narrative text, brief_md text | FK; unique(decision_id, version). The current assessment is the highest version; lower versions are superseded (derived, no stored flag). Migration 0004 added the hash, fingerprint and as-of columns. An assessment is immutable once written: only narrative and brief_md may change |
| `recommendations` | Next Best Evidence actions | id, assessment_id, action_type, description, effort_days numeric, expected_reduction numeric, relevance numeric, priority_score numeric, dimensions_addressed text[], blockers_resolved int (migration 0004), status enum(proposed, accepted, rejected, deferred), human_note | FK. For INSUFFICIENT assessments `expected_reduction = 0` and `blockers_resolved` holds the number of gating blockers addressed |
| `decision_reviews` | Reviewer and human reviews | id, assessment_id, reviewer_type enum(agent, human), reviewer_id null, verdict enum(ready, needs_rework), challenges jsonb (array of {type, severity, target_type, target_id, text}), human_response text | FK |
| `agent_runs` | Execution log | id, decision_id, assessment_id, stage enum(dq, quant, customer, experiment, synthesis, review, brief), agent_name, status, input jsonb, output jsonb, model, prompt_version, tokens_in, tokens_out, latency_ms, error | idx(assessment_id, stage) |
| `audit_logs` | Immutable trail | id, org_id, actor_type, actor_id, action, entity_type, entity_id, before jsonb, after jsonb, ts | idx(entity_type, entity_id); insert-only |

### 14.2 Views

- `v_traceability_matrix` (section 10)
- `v_debt_radar` (portfolio: decision, team, type, DDI, band, state, age, last assessed), for Power BI
- `v_evidence_freshness`, `v_nbe_ranking`, `v_agent_quality` (eval metrics) for Power BI
- `v_evidence_health` (descriptive evidence-base summary, §24). Built from existing tables only. **No new tables were added for Evidence Health, Canvas or Lifecycle.** Lifecycle transitions are recorded in `audit_logs`. Field-level canonical ERD: [ERD.md](ERD.md)
- Read-only analytical views over `fc_` data for the SQL-guard allow-list.

### 14.3 ERD (text)

```
organizations 1─* teams 1─* users
organizations 1─* data_sources 1─* metrics 1─* metric_observations
organizations 1─* decisions *─1 metrics (success_metric)
decisions 1─* evidence *─1 evidence_sources *─0..1 data_sources
evidence *─0..1 analysis_results | experiments | customer_insights | metrics
decisions 1─* experiments 1─* experiment_results
decisions 1─* decision_assessments 1─* claims *─* evidence (claim_evidence)
decision_assessments 1─* decision_reviews | recommendations | dq_checks
decisions 1─0..1 decision_records
decisions 1─* agent_runs 1─* analysis_results
every entity ─* audit_logs
```

## 15. Agent Responsibilities

**Architecture:** 4 agents, 7 UI-visible pipeline stages. Plain Python state machine, Anthropic SDK with tool use and Pydantic-validated structured output, no agent framework. **Models:** Claude Sonnet for the primary workflow (Orchestrator planning, Analytics, Synthesis) and Claude Opus for the Reviewer/Critic and other critical reasoning where practical and available (fallback to Sonnet with a flagged log entry if not). No other provider.

**Stage → agent mapping**

| UI stage | Executed by | Nature |
|---|---|---|
| 1 Data Quality | Data & Analytics | Mostly deterministic checks, LLM only summarizes |
| 2 Quantitative Analysis | Data & Analytics | Validated SQL + stats |
| 3 Customer Evidence | Evidence Synthesis (customer-insight capability) | LLM theme/sentiment extraction, counts computed in code |
| 4 Experiment Evidence | Data & Analytics (experimentation capability) | Statistical code. LLM drafts plan text only |
| 5 Evidence Synthesis | Evidence Synthesis | Claims, gaps, recommendation text |
| 6 Adversarial Review | Reviewer/Critic | Independent critique |
| 7 Decision Brief | Evidence Synthesis | Template + validated claims |

**Agent specifications**

### A1. Orchestrator
- **Purpose:** run the pipeline in order and handle state.
- **Responsibilities:** create the assessment, schedule stages, enforce gates (e.g. stop quantitative analysis on critical DQ failure for the success metric), handle retries and partial status, compute the DDI by calling the engine, compute NBE, write audit logs.
- **Inputs:** decision ID. **Outputs:** assessment record with per-stage status.
- **Tools:** stage runners, DDI engine, NBE engine, DB.
- **Permissions:** metadata read/write for pipeline tables. No raw data access.
- **Failure modes:** skipped stage, loops, silent partial results.
- **Evaluation:** stage completion rate, correct gating on seeded DQ defect, idempotent re-run.
- **Should NOT act:** to produce analysis or prose itself. To proceed past a failed gate. To choose the DDI.

### A2. Data & Analytics Agent
- **Purpose:** assess data quality and answer quantitative questions rigorously. Also performs experiment analysis.
- **Responsibilities:** DQ checks, generate/execute allow-listed SQL, trend/segmentation/funnel/retention, SRM/effect/CI/power calculations, anomaly flag (stretch), heterogeneity / aggregate-masking check.
- **Inputs:** metric definitions, schema catalog, analysis spec. **Outputs:** structured `analysis_results` with query, n, effect, CI, limitations, DQ status.
- **Tools:** `profile_table`, `run_readonly_sql` (sqlglot-validated: SELECT only, view allow-list, LIMIT, statement timeout), stats functions.
- **Permissions:** read-only DB role on reporting/`fc_` views. Writes only `analysis_results`/`dq_checks` through service functions.
- **Failure modes:** wrong joins, hallucinated columns, p-hacking, small-cell noise, multiple comparisons.
- **Evaluation:** SQL validity rate, golden-answer accuracy, DQ defect detection (seeded), SRM detection.
- **Should NOT act:** on non-allow-listed objects. On a data source with open critical DQ failure (it reports instead). Claim causation. Run unbounded fishing across segments without correction.

### A3. Evidence Synthesis Agent
- **Purpose:** turn analyses, experiments and customer data into cited claims, gaps, recommendation text and the brief.
- **Responsibilities:** customer theme/sentiment extraction, stance classification, claim generation with evidence IDs, gap identification vs the checklist, NBE candidate suggestions and rationale, brief drafting, experiment plan/PRD-lite drafting.
- **Inputs:** evidence records, analysis results, customer text, DQ results. **Outputs:** Pydantic-validated `claims`, `claim_evidence`, classification fields, narrative, candidate actions.
- **Tools:** `get_evidence`, `search_customer_text` (synthetic corpus, bounded), template renderer.
- **Permissions:** read-only on evidence. Writes draft claims and narrative only.
- **Failure modes:** fabricated citations, stance misclassification, over-generalization from few quotes, causal language.
- **Evaluation:** citation validity (code-enforced), stance accuracy vs labels, theme precision/recall on labelled synthetic text, absence of causal language without BR-7 support.
- **Should NOT act:** without evidence (it states "insufficient evidence"). On numbers (it quotes computed values only). On the DDI.

### A4. Reviewer / Critic Agent
- **Purpose:** adversarially challenge the synthesis and DDI explanation. Independent of the author (different prompt, Opus).
- **Responsibilities:** check causation language, selection bias, survivorship, small n, stale evidence, single-source dependence, cherry-picking, hidden contradictions, aggregate-vs-segment masking, unsupported financial claims, and whether INSUFFICIENT EVIDENCE was respected.
- **Inputs:** claims, evidence, analyses, DDI breakdown. **Outputs:** structured challenges and verdict (`ready` / `needs_rework`).
- **Tools:** read-only evidence/analysis fetch, rule checklist.
- **Failure modes:** rubber-stamping, over-flagging, flagging without target.
- **Evaluation:** seeded-flaw recall, false-flag rate on clean scenarios, severity calibration.
- **Should NOT act:** to edit claims or scores. To raise a challenge without a target claim/evidence ID.
- **Day-3 interface (agent not implemented yet):** reviews are stored in `decision_reviews` with `reviewer_type` `agent` or `human`. Day 3 provides the **human review** endpoint (verdict, reason, actor, timestamp), the `assessed` to `challenged` transition and the validation/override rules (BR-13), so the Day-5 Reviewer plugs into an existing workflow. The Reviewer may later feed NBE relevance. Day 3 does not.

**Common safeguards:** structured outputs validated by Pydantic. One repair retry, then fail to "partial". All calls logged in `agent_runs` with prompt version. Temperature low for classification. Retrieved text is treated as data, never as instructions (prompt-injection hygiene on customer text).

## 16. Analytics Requirements

| Capability | Business question | Required data | Metric / calculation | Output | Limitations |
|---|---|---|---|---|---|
| **Data quality** | Can we trust the data? | Source tables | Completeness %, duplicate rate, FK integrity, event-sequence validity, daily volume z-score by event/platform, tracking-gap detection | pass/warn/critical per check | Rules cover known failure shapes only |
| **Trend** | Is the metric moving? | Daily/weekly observations | Rolling mean, OLS slope with CI, change vs baseline | Series + slope + CI | Seasonality, short windows |
| **Segmentation** | Who is affected? Does the aggregate hide differences? | Events × user attributes | Metric by segment, gap vs overall, heterogeneity / aggregate-masking flag (segment effects that differ materially from each other or from the aggregate, by ≥ X pp or in sign), minimum cell size | Segment table, flag | Small cells, multiple comparisons |
| **Funnel** | Where do users drop? | Ordered events | Step conversion, drop-off | Funnel table | Attribution windows, tracking defects |
| **Retention** | Do users stay? | Signup + activity | Cohort D7/D30/D90 retention | Cohort matrix, curves | Cohort size, definition of "active" |
| **Experiment analysis** | Did the change cause the effect? | Assignments, outcomes | SRM chi-square, effect, CI, p, power vs MDE, design rank | Effect with CI, integrity flags | Peeking, novelty, underpower |
| **Customer evidence** | What do customers say? | Survey/reviews/tickets (synthetic) | Theme counts, sentiment share, segment split, sampled quotes | Theme table | Self-selection, LLM classification error (sampled audit) |
| **Evidence comparison** | Do sources agree? | Evidence stances | Stance matrix by type, concentration | Agree/conflict table | Depends on stance labels |
| **Anomaly (stretch)** | Is there a spike/drop? | Time series | Z-score vs trailing window | Flag list | False positives |
| **Revenue impact** | Is business impact quantified? | Subscription + price data | Scenario model with sensitivity range, sourced from evidence | Range table | Assumed elasticity. Never presented as observed. |

**Statistical hygiene rules:** report effect sizes and CIs, not p-values alone. Minimum cell sizes. Multiple-comparison note on segment scans. All analyses store query and params for reproducibility.

## 17. KPI Definitions

**Product KPIs**

| KPI | Definition |
|---|---|
| Time-to-assessment | Median time from "Run Assessment" to completed brief, vs a manual baseline estimate (documented as an estimate) |
| Assessment coverage | % of registered decisions with ≥1 completed assessment |
| Traceability rate | % of claims with ≥1 valid evidence ID, one source (and one analysis where quantitative). Target 100% |
| NBE acceptance rate | accepted ÷ (accepted + rejected) recommendations |
| Observed DDI reduction | Mean DDI change between consecutive assessments after an accepted NBE action |
| Insufficient-evidence rate | % of assessments returning INSUFFICIENT EVIDENCE (monitored, not minimized) |
| Acknowledged-risk decisions | % of decisions recorded while High/Critical/INSUFFICIENT with explicit acknowledgement |

**System-quality KPIs**

| KPI | Definition |
|---|---|
| SQL validity rate | % generated queries that parse, pass the guard and execute |
| Golden-answer accuracy | % analyses matching expected values within tolerance |
| DQ detection recall | Seeded defects detected ÷ seeded defects |
| Reviewer recall / false-flag rate | Seeded flaws flagged ÷ seeded flaws. Flags on clean scenarios ÷ total flags |
| Citation validity | % of generated claims citing existing evidence IDs before filtering. Post-filter must be 100% |
| DDI reproducibility | Identical inputs → identical output (100%) |

**Portfolio KPIs (Power BI)**
Debt by team and decision type. DDI distribution by band. Evidence freshness distribution. Open DQ issues. Decisions decided while High/Critical. Time since last assessment.

## 18. Acceptance Criteria

Format: Given / When / Then. All must pass for MVP sign-off.

| ID | Criterion |
|---|---|
| AC-1 | **Given** a registered decision with sufficient evidence, **when** I run an assessment, **then** all 7 stages appear in the UI with status, and a DDI with a 9-dimension breakdown is shown. |
| AC-2 | **Given** the Onboarding scenario with the seeded tracking defect, **when** I run an assessment, **then** the state is INSUFFICIENT EVIDENCE, no numeric DDI is displayed, the blocking DQ finding is named, and NBE ranks the instrumentation fix. |
| AC-3 | **Given** any generated claim, **when** I open the traceability matrix, **then** the claim resolves to ≥1 evidence ID and a source (and an analysis if quantitative). |
| AC-4 | **Given** the AI Coach scenario, **when** the Reviewer runs, **then** it flags correlation-vs-causation and selection bias, and the brief does not use causal language. |
| AC-5 | **Given** the Community scenario, **when** segmentation runs, **then** the heterogeneity / aggregate-masking flag fires on materially divergent segment effects, the contradiction penalty floor applies, the Reviewer flags that the aggregate conceals segment differences, and NBE recommends segment-aware validation. (No textbook Simpson's paradox sign reversal is required.) |
| AC-6 | **Given** the Pricing scenario, **when** the assessment runs, **then** the inconclusive experiment is graded appropriately and is not listed as support. |
| AC-7 | **Given** identical evidence and parameters, **when** the DDI is computed twice, **then** results are identical. Changing LLM output text does not change the score. |
| AC-8 | **Given** a DDI result, **when** I open sensitivity, **then** I see the range under weight/penalty perturbations and a robust/sensitive label. |
| AC-9 | **Given** an assessment, **when** I open Next Best Evidence, **then** I see ≥3 actions (or a stated reason none apply) compared on effort, expected reduction, relevance and priority, each with a "why". |
| AC-10 | **Given** an LLM claim with no valid evidence ID, **when** the output is validated, **then** it is discarded and logged, not shown. |
| AC-11 | **Given** generated SQL that is non-SELECT or references a non-allow-listed object, **when** executed, **then** it is rejected and logged. |
| AC-12 | **Given** a Reviewer verdict "needs rework", **when** I try to finalize the brief, **then** I am blocked unless I override with a reason (logged). |
| AC-13 | **Given** the role-switcher, **when** I change persona, **then** permitted actions change per the persona table. |
| AC-14 | **Given** a High/Critical or INSUFFICIENT decision, **when** I record a decision, **then** an explicit acknowledgement and rationale are required. |
| AC-15 | **Given** any screen, export or Power BI page showing FitConnect data, **then** it is visibly labelled "Synthetic data". |
| AC-16 | **Given** the repo, **when** I run the documented setup, **then** the DB, seed data and app start locally, and the Power BI file connects to the reporting views. |
| AC-17 | **Given** a failed or timed-out stage, **then** the assessment is marked "partial" with the failing stage shown, never silently complete. |
| AC-18 | Documentation states the DDI is a proposed framework and not an industry standard. |
| AC-19 … AC-24 | Lifecycle acceptance criteria: see §23.4 |
| AC-25 … AC-29 | Evidence Health acceptance criteria: see §24.6 |
| AC-30 … AC-36 | DDI transparency acceptance criteria: see §25.4 |
| AC-37 … AC-42 | Decision Canvas acceptance criteria: see §26.5 |
| AC-43 | Positioning: product UI, brief template, README and Power BI report contain the "evidence-risk heuristic" statement and none describe DDI as validated, objective, standard or predictive. |

## 19. Evaluation Strategy

**Layers**

1. **Unit tests:** DDI engine (property tests: monotonic in evidence quality, deterministic, gating), SQL guard (injection/DDL/DML/unsafe-view cases), NBE scoring, stats functions vs known values.
2. **Data tests:** generator reproducibility (fixed seed), defect manifest check (seeded defects exist as documented).
3. **Agent evaluation suite (~20 scenarios)** in `tests/evals/`, built from the four scenarios (+ variants: DQ-fixed onboarding, clean "strong evidence" decision, empty-evidence decision, contradictory-evidence variant, stale-evidence variant, injection-in-customer-text variant). Each defines expected state, DDI band, required reviewer flags, required NBE actions.
4. **Metrics:** those in section 17 (system-quality KPIs). Reported in a table in the README and in Power BI `v_agent_quality`.
5. **LLM-specific checks:** citation validity, causal-language scan, schema-validity rate, repair-retry rate, refusal correctness on insufficient evidence, prompt-injection resistance.
6. **Human spot-audit:** the Product Owner reviews a sample of claims and challenges per scenario (recorded in docs).
7. **Regression:** the suite runs on every prompt/parameter version change. Versions are recorded in `agent_runs`.

**Pass thresholds (initial targets):** DDI reproducibility 100%. Citation validity post-filter 100%. SQL guard test pass 100%. DQ seeded-defect recall ≥ 90%. Reviewer seeded-flaw recall ≥ 80% with ≤ 20% false flags on clean scenarios. Expected-state match 100% on the four core scenarios.

**Honest reporting:** results, including failures, are documented in `docs/evaluation-report.md`. Eval prompts and labels are synthetic and say so.

## 20. Seven-Day Implementation Plan

*Implementation does not begin until this PRD is approved.*

| Day | Focus | Exit criteria |
|---|---|---|
| **1** | Approve PRD. Finalize docs: DDI spec, business rules, traceability spec, NBE spec, ERD, ADRs, stakeholder/process models. Repo setup, Docker Compose skeleton. | Docs approved by PO |
| **2** | PostgreSQL schema + migrations, `fc_` synthetic generator with scenario patterns and defect manifest, CSV loaders, reporting views | Seed loads reproducibly. Manifest verifiable |
| **3** | FastAPI CRUD, role-switcher, audit logging, **DDI engine + sensitivity + gating with unit tests**, NBE engine | DDI runs on hand-built evidence. Gating tests pass |
| **4** | Data & Analytics Agent (DQ, SQL guard, 6 analyses, experiment stats), Orchestrator, stages 1, 2, 4 end to end | Onboarding returns INSUFFICIENT. Community flags heterogeneity |
| **5** | Evidence Synthesis + Reviewer agents, structured outputs, citation filter, traceability matrix view, brief generation, NBE integration | Full 7-stage flow on all four scenarios |
| **6** | Next.js UI (pipeline view, DDI breakdown, matrix, NBE table, reviewer panel, decision form, role-switcher). **Power BI dashboard on reporting views** | Demoable UI + .pbix |
| **7** | Eval suite (~20 scenarios) + report, README, demo script, screenshots, polish, buffer. Optional hosting only if everything else is stable | All acceptance criteria evidenced |

**Cut order if behind (Power BI is NOT cut):** hosted demo → PRD-lite generator → anomaly flag → UI polish (keep functionality) → eval scenario count (never the four core scenarios).

**Key risks:** scope creep, LLM variance (mitigated by structured output + deterministic engine), synthetic data realism (mitigated by seeded manifest), time on Power BI (mitigated by building views on Day 2–3 and mockups early).

## 21. Final Architecture

```
┌─────────────┐   HTTP/JSON   ┌───────────────────────────────┐   SQL    ┌──────────────────────────┐
│ Next.js UI  │ ────────────> │ FastAPI                       │ ───────> │ PostgreSQL               │
│ (role       │               │  ├─ API + role checks         │          │  ├─ core schema          │
│  switcher)  │               │  ├─ Orchestrator (state mach.)│          │  ├─ fc_ (synthetic data) │
└─────────────┘               │  ├─ Data & Analytics agent    │          │  └─ reporting views      │
                              │  ├─ Evidence Synthesis agent  │          └────────────┬─────────────┘
                              │  ├─ Reviewer agent            │                       │
                              │  ├─ DDI engine (pure Python)  │                       ▼
                              │  ├─ NBE engine (pure Python)  │               Power BI Desktop
                              │  └─ SQL guard (sqlglot)       │               (reporting views)
                              └──────────────┬────────────────┘
                                             │ Anthropic SDK
                                             ▼
                              Claude Sonnet (workflow) / Claude Opus (review)
```

**Technology:** Python 3.11, FastAPI, SQLAlchemy + Alembic, Pydantic, sqlglot, scipy/statsmodels, pandas, pytest, PostgreSQL 16, Next.js (TypeScript), Docker Compose (local), Power BI Desktop, Git/GitHub, Anthropic SDK. **No** Kubernetes, microservices, queues, agent frameworks or other LLM providers.

**Key architecture decisions (ADR summary)**

| ADR | Decision |
|---|---|
| 1 | Four agents, seven visible stages |
| 2 | Plain Python orchestration, no agent framework |
| 3 | Deterministic DDI. LLM never sets numbers |
| 4 | INSUFFICIENT EVIDENCE as a first-class state |
| 5 | Industry-agnostic core, `fc_` schema isolates demo data |
| 6 | Read-only allow-listed SQL with sqlglot validation |
| 7 | Claude only: Sonnet primary, Opus for review |
| 8 | CSV-only ingestion, role-switcher instead of auth |
| 9 | Local-first. Hosting optional after stability |
| 10 | Traceability and NBE as first-class modules |

**Repository structure**

```
Decision_Debt_Radar/
├── README.md
├── docs/            PRD, DDI spec, traceability spec, NBE spec, ERD, ADRs, evaluation report
├── prompts/         versioned agent prompts and output schemas
├── data/            synthetic generator, seed CSVs, defect/pattern manifest
├── database/        migrations, views, seed SQL
├── backend/         FastAPI, DDI + NBE engines, services
├── agents/          orchestrator, analytics, synthesis, reviewer, tools, SQL guard
├── frontend/        Next.js app
├── analytics/       notebooks, SQL libraries, Power BI file, KPI definitions
└── tests/           unit, SQL guard, DDI, evals
```

## 22. Out-of-Scope Items

- Real authentication, SSO, multi-tenant isolation, billing.
- Live data connectors (only CSV ingestion).
- Real-time or streaming data.
- Automated decision-making or execution of decisions.
- A causal-inference engine (only design-rank rules and Reviewer checks).
- Other LLM providers or fine-tuning.
- Real customer data. Any non-synthetic data.
- Industries other than the FitConnect demo (schema supports them, none shipped).
- Mobile app.
- Empirical calibration/validation of DDI weights against real outcomes.
- Production hosting, SLAs, security hardening beyond demo level (public hosting is optional and only after the core is stable).
- Claiming Decision Debt or the DDI as an industry standard, a validated score, or an outcome predictor.
- **Outcome Observed, outcome attribution, post-decision re-assessment loops and any outcome tracking** (future, §23.3 and §29).
- Any additional agent beyond the four. Any new pipeline stage beyond the seven.
- A second scoring system. Evidence Health is descriptive and has no composite score.
- A standalone Decision Canvas product. It is a form on the decision object.
- Everything listed in §29 Future Product Analytics.

---

## 23. Decision Lifecycle

*Canonical detail, transition guards and audit events: [decision-lifecycle.md](decision-lifecycle.md).*

### 23.1 Lifecycle stages

```
Decision Created → Evidence Gathered → Assessment Run → Evidence Challenged
      → Decision Validated → Human Decision Recorded
                                   ┆ (future scope below this line)
                      → Outcome Observed → Re-assessment
```

| # | Stage | Purpose | In MVP? |
|---|---|---|---|
| 1 | **Decision Created** | Define what is being decided, the hypothesis, the success metric, the deadline, the risk and what would change our mind (Decision Canvas) before any evidence is assessed. | Yes |
| 2 | **Evidence Gathered** | Link sources, metrics, experiments and customer data. Make the evidence base explicit and inspectable. | Yes |
| 3 | **Assessment Run** | Execute the seven-stage pipeline. Produce the DDI or INSUFFICIENT EVIDENCE, claims, traceability matrix and Next Best Evidence. | Yes |
| 4 | **Evidence Challenged** | The Reviewer/Critic adversarially tests the synthesis. Humans may respond to challenges. | Yes |
| 5 | **Decision Validated** | The *assessment* has passed adversarial review (verdict `ready`, or `needs_rework` overridden by a human with a reason). **It does not mean the decision is correct.** It means the brief is fit to put in front of the decider. | Yes |
| 6 | **Human Decision Recorded** | A human records approve, reject, defer or approve-with-conditions plus rationale, acknowledging risk where required. | Yes (**last MVP stage**) |
| 7 | **Outcome Observed** | After the decision is implemented, record what actually happened and attribute it. | **Future. Not MVP** |
| 8 | **Re-assessment** | Revisit the decision and its evidence in light of outcomes and new evidence. | **Future. Not MVP** |

### 23.2 Why the lifecycle matters
The eventual product vision is not to assess evidence once. It is to let an organization eventually **learn whether evidence-backed decisions produced better outcomes**, and to refine its evidence standards from that learning. The MVP deliberately builds the first six stages only. It records enough (the assessment version, DDI parameter version, evidence snapshot and the human decision record) that the future stages can be added without re-modelling.

### 23.3 MVP boundary (explicit)
- Implemented: stages 1–6 (through *Human Decision Recorded*).
- **Not implemented, not stubbed in UI, no tables:** Outcome Observed, outcome attribution, post-decision re-assessment, outcome metrics. These appear only in the roadmap and §29.
- "Re-running an assessment" **before** a decision is recorded is MVP behavior (new assessment version, FR-30). It is not the future "Re-assessment" stage, which is outcome-informed.
- The lifecycle is held in `decisions.lifecycle_stage`. Transitions are written to `audit_logs`. No additional tables.

### 23.4 Lifecycle acceptance criteria (MVP transitions only)

| ID | Criterion |
|---|---|
| AC-19 | **Given** a new decision, **when** the canvas passes validation (§26), **then** the stage is `created`. A decision with an invalid canvas cannot advance. |
| AC-20 | **Given** a `created` decision, **when** its success metric has a registered data source or ≥1 evidence item is linked, and the user confirms, **then** it moves to `evidence_gathered`. Otherwise the transition is rejected with the reason. |
| AC-21 | **Given** an `evidence_gathered` decision, **when** an assessment completes (state `scored` or `insufficient_evidence`), **then** the stage is `assessed`. A `partial` assessment leaves the stage unchanged and shows the failed stage (AC-17). |
| AC-22 | **Given** an `assessed` decision, **when** the Reviewer completes, **then** the stage is `challenged` and the verdict is stored. |
| AC-23 | **Given** a `challenged` decision, **when** the verdict is `ready`, or `needs_rework` is overridden by a human with a reason, **then** the stage is `validated`. Otherwise it stays `challenged`. |
| AC-24 | **Given** a `validated` decision, **when** a human records a decision (acknowledgement and rationale if High/Critical/INSUFFICIENT), **then** the stage is `decided` and the record is immutable in the MVP. Attempts to skip a stage, or to record a decision by a persona without permission, are rejected. Every transition writes an audit log row. Adding evidence or editing the canvas after `assessed` marks the assessment stale and returns the stage to `evidence_gathered` (the canvas rule is a database invariant; a data-quality status change is treated like an evidence change). The `validated` stage is displayed as exactly "Assessment validated by review". |

## 24. Evidence Health

*A descriptive monitoring view. It is not a second score and does not compete with DDI.*

### 24.1 Definition
**Evidence Health** summarizes the condition of an organization's evidence base (across its decisions, teams and sources) as a set of independent descriptive indicators, built from data already in the architecture.

### 24.2 Purpose
DDI answers "how well is *this decision* supported?" Evidence Health answers "what is the general state of our evidence base, and where are the systemic weak spots?" It serves BizOps and department leaders monitoring the portfolio, and it is a Power BI page.

### 24.3 Dimensions
Each dimension is reported **separately**. There is **no composite number**.

| Dimension | Meaning | Reuses |
|---|---|---|
| Freshness | Share of active evidence items within their type's half-life | D3 inputs, `evidence.observed_end`, half-life parameters |
| Recency | Days since the newest evidence item per decision, and days since each data source's last load | `evidence`, `data_sources.last_loaded_at` |
| Reliability | Share of items with source tier 1–2 and grade A–B | D1 inputs |
| Coverage | Mean checklist coverage across active decisions | D2 inputs |
| Data-quality status | Share of data sources with open warn/critical `dq_checks` | `dq_checks` |
| Source diversity | Distinct sources per evidence item and source concentration (HHI) | P2 concentration inputs |
| Contradiction | Share of active decisions where contradiction weight exceeds a display threshold | P1 inputs |

*Freshness vs Recency:* Freshness is relative to each evidence type's expected shelf life (a percentage). Recency is the raw elapsed time since newest evidence or last data load. They are shown side by side because they diagnose different problems.

### 24.4 Calculation approach
- One SQL view, `v_evidence_health`, in long format: `org_id, team_id, decision_type, dimension, metric_name, value, indicator, as_of_date, is_synthetic`.
- Values are computed from existing tables and the same parameter version used by the DDI engine. **No duplicated logic:** shared calculations (freshness, tier/grade factors, HHI) are implemented once as SQL functions or views that the DDI inputs also consume where practical. Otherwise the view is validated against the engine's unit-test fixtures.
- `indicator` is a green/amber/red display convention per dimension from configurable thresholds. Indicators are never aggregated across dimensions.
- Grain: organization × team × decision_type, plus a per-decision drill-through.

### 24.5 MVP scope
- **Must:** `v_evidence_health` view and a Power BI page (cards per dimension, breakdown by team and decision type, trend by `as_of_date` if time permits, drill-through to the debt radar).
- **Should:** a read-only summary table in the app (a few cards). Skipped first if time is short.
- **Not in MVP:** alerts, notifications, scheduled snapshots, forecasting, a composite score, new agents, new tables.
- Snapshot over time uses the existing `as_of_date` computed on demand from current data. Historical snapshots are future scope.

### 24.6 Acceptance criteria

| ID | Criterion |
|---|---|
| AC-25 | `v_evidence_health` exists and returns one row per org × team × decision_type × dimension for the seeded data. |
| AC-26 | Each dimension value is reproducible from the underlying tables (spot-checked against a hand-calculated fixture). |
| AC-27 | No view, page or API returns a single combined "evidence health score". |
| AC-28 | The Power BI page loads from the view, shows all seven dimensions, supports filtering by team and decision type, and carries the "Synthetic data" label. |
| AC-29 | Changing a data source's last load date, or marking a DQ check resolved, changes the relevant indicator without any code change. |

## 25. DDI Transparency (first-class UX requirement)

The user must **never see a bare "DDI = 63"**. The DDI is only ever rendered through the **DDI panel**. This section specifies the **information hierarchy**, not pixel-level design.

### 25.1 Information hierarchy (top to bottom)

```
DECISION DEBT INDEX            (label: "evidence-risk heuristic, not a measure of decision quality")
  63 / 100            HIGH               Parameter version: ddi_params_v0.1

  What drove this result (2–4 plain-language sentences, generated from computed values)

  DIMENSION BREAKDOWN  (each shows dimension score, and its contribution to the debt)
    Evidence Quality
    Evidence Coverage
    Freshness
    Experimental Strength
    Customer Evidence
    Behavioral Evidence
    Financial Evidence
    (Non-applicable dimensions are listed as "not applicable for this decision type", with weights renormalized)

  PENALTIES
    Contradiction   (score, resulting contribution, items driving it)
    Uncertainty     (score, resulting contribution, components: CI width / small n / concentration)

  SENSITIVITY
    Range: X–Y
    Band stable: YES / NO        → "Robust" or "Sensitive"
    Which perturbation moved it most

  WHAT IS MISSING OR WEAK  (gaps vs checklist, lowest-scoring dimensions, open DQ issues)

  WHAT WOULD REDUCE THE DEBT?
    Ranked Next Best Evidence actions (priority, effort, expected reduction, relevance, why)
```

**Insufficient evidence variant:** the panel shows "INSUFFICIENT EVIDENCE" instead of a number. It lists the blocking reasons (BR-1 to BR-3), what is missing or blocked, and the ranked actions that would unblock scoring. No numeric score, estimate, or range is shown.

### 25.2 Requirements
- FR-26 (above) and: every value in the panel is traceable to the stored `decision_assessments` row (`dimension_scores`, `penalty_scores`, `sensitivity`, `params_version`). The UI performs no scoring.
- The "what drove this result" text is generated from computed values (largest contributions first), with numbers inserted by code. The LLM may phrase it but cannot supply numbers (BR-5).
- Each breakdown line links to the evidence items behind that dimension (traceability).
- The panel is the same component in the app, the brief and the export. The Power BI page shows the same breakdown fields.
- Color is never the only signal for the band (NFR-10).

### 25.3 Why this matters
The numeric score is the least valuable part of DDI. The auditable decomposition is the value (see §27). A UI that emphasized the number alone would invite exactly the false-precision reading we want to avoid.

### 25.4 Acceptance criteria

| ID | Criterion |
|---|---|
| AC-30 | Every place a numeric DDI is displayed (app, brief, export, Power BI) is accompanied by the band, the seven dimension rows, both penalties and the parameter version. A bare number is a defect. |
| AC-31 | The panel shows each dimension's score **and** its contribution to total debt, and the contributions plus penalty contributions sum to the displayed DDI (±rounding, verified by test). |
| AC-32 | The panel shows the sensitivity range, a YES/NO "Band stable" indicator and the robust/sensitive label. |
| AC-33 | The panel shows a concise "what drove this result" explanation and a "what is missing or weak" list. |
| AC-34 | The panel shows the ranked Next Best Evidence actions under "What would reduce the debt?". When none apply, it states why. |
| AC-35 | For INSUFFICIENT EVIDENCE, no numeric value appears anywhere. The blocking reasons and unblocking actions appear instead. |
| AC-36 | The positioning label (§27) is visible on the panel, and the explanatory text contains only code-computed numbers. |

## 26. Decision Canvas

*Canonical field spec and validation: [decision-canvas.md](decision-canvas.md).*

**Purpose.** A lightweight PM/BA artifact in the decision-creation workflow that forces the decision owner to define the decision and its success criteria **before** evidence is assessed. It is a form on the Decision object, not a separate feature.

### 26.1 Fields

| Canvas question | Decision field | Type | Required |
|---|---|---|---|
| What are we deciding? | `title`, `description` | text | Yes |
| What is the hypothesis? | `hypothesis` | text (structured prompt "If we … then … because …") | Yes |
| What is the success metric? | `success_metric_id` | FK → metrics | Yes |
| When must the decision be made? | `decision_due_date` | date | Yes |
| Risk level | `risk_level` | enum low/medium/high | Yes |
| Current evidence | `current_evidence_notes` (+ evidence linked in the register) | text | Optional (recommended) |
| What evidence would change our mind? | `change_my_mind_criteria` | 1–5 short statements | Yes |

Also captured: `decision_type` (drives the coverage checklist) and `team_id`/`owner_id`.

### 26.2 Validation rules
- CV-1 All required fields present.
- CV-2 Hypothesis is falsifiable in form: it must name a measurable outcome. The UI checks that it references the selected success metric by name or a direction (increase/decrease), as a soft check with a warning, not a block.
- CV-3 Success metric must exist and have a definition. If it has no linked data source, a warning notes that quantitative evidence will depend on manually linked evidence.
- CV-4 `decision_due_date` must be today or later at creation.
- CV-5 At least one "change my mind" criterion. Each 10–300 characters.
- CV-6 `decision_type` must be one of the configured types, which determine the required-evidence checklist (DDI-spec).
- CV-7 The canvas is **locked at first assessment** (`canvas_locked_at`). Later edits are allowed but audit-logged, flagged as "canvas changed after assessment" on the brief, and mark the assessment stale.

### 26.3 Connection to the pipeline
The canvas feeds the Orchestrator (success metric, decision type, risk level), the Synthesis agent (hypothesis, change-my-mind criteria, current evidence notes) and the Reviewer (checks whether the evidence meets or fails each criterion, and whether the hypothesis is being read generously). The brief reports on each criterion as *met / not met / not testable with available evidence*.

### 26.4 MVP scope
One form (about seven fields), validation, locking, audit logging, and the criteria report in the brief. No templates library, no versioned canvases, no collaboration features.

### 26.5 Acceptance criteria

| ID | Criterion |
|---|---|
| AC-37 | **Given** missing required canvas fields, **when** I try to create the decision, **then** creation is blocked with field-level errors. |
| AC-38 | **Given** a valid canvas, **when** I save, **then** a decision is created with all canvas fields stored on the decision record. |
| AC-39 | **Given** a hypothesis that does not reference a measurable outcome, **then** a warning is shown and I may proceed. |
| AC-40 | **Given** a success metric without a data source, **then** a warning is shown. |
| AC-41 | **Given** the first assessment starts, **then** the canvas is locked. A later edit is audit-logged, flagged on the brief and marks the assessment stale. |
| AC-42 | **Given** an assessment, **when** the brief is generated, **then** each change-my-mind criterion is reported as met, not met or not testable, with evidence references where applicable. |

## 27. DDI Positioning and Limitations

> **DDI is a transparent evidence-risk heuristic for business decisions.**
> *The value of DDI is primarily in decomposing evidence quality, coverage, freshness, experimental strength, customer/behavioral/financial evidence, contradiction and uncertainty into an auditable framework. The numeric score is a configurable heuristic and should be interpreted within an organization's configuration.*

**DDI is not:** an objective measure of decision quality · a scientifically validated universal score · an industry standard · a predictor of business outcomes.

**Consequences for the product**
- A high DDI means "the evidence we have is weak, thin, stale, conflicted or missing". It does not mean the decision is wrong. A low DDI does not mean the decision is right.
- Scores are comparable only within one organization's configuration and parameter version. Cross-organization comparison is not supported.
- The mathematical model is unchanged. Weights and coefficients remain documented assumptions with sensitivity analysis as a **core safeguard** (reported on every scored assessment).
- Positioning text appears in the UI (FR-29), brief template, README, Power BI report and the evaluation report (AC-43).
- Interview framing: the contribution is the **auditable decomposition**, the **gating (insufficient evidence)**, the **transparency** and the **workflow**, not a claim of a "true" score.

## 28. Portfolio Demonstration Narrative

**Central message:** *"Decision Debt Radar does not decide for you. It tells you how well your decision is supported, what could invalidate your reasoning, and what evidence you should gather next."*

**Demo story (about 8–10 minutes; the AI Coach decision is the lead scenario)**

1. **A human creates an important business decision** (a PM role).
2. **The Decision Canvas** defines what is being decided, the success metric and *what evidence would change the decision*.
3. **DDR checks whether the underlying data can be trusted** (Data Quality stage). The Onboarding scenario shows a tracking defect and an honest INSUFFICIENT EVIDENCE.
4. **DDR performs quantitative analysis** (trend, segmentation, funnel, retention).
5. **DDR examines customer and experiment evidence** (themes, SRM, CI, power).
6. **DDR synthesizes supporting, contradictory and missing evidence**, with every claim traceable (the traceability matrix).
7. **The Reviewer challenges unsupported reasoning** (correlation vs causation, selection bias, aggregate-hides-segments).
8. **DDR computes a transparent DDI**: breakdown, penalties, parameter version, sensitivity.
9. **DDR identifies the Next Best Evidence** ranked by priority.
10. **A human records the final decision and rationale.** The Power BI Debt Radar and Evidence Health pages show the portfolio view.

**Framing guardrails:** present DDR as decision-governance and evidence-risk tooling. Do not call it an AI chatbot, AI dashboard or generic AI analytics tool. State plainly that all FitConnect data is synthetic and that DDI is a proposed heuristic. Talking points per skill area (BA, PM, analytics, AI) live in `docs/` and the README demo script.

## 29. Future Product Analytics (not MVP)

Future versions, once the Outcome Observed and Re-assessment stages exist (§23), could measure:

- the decision-to-outcome relationship
- DDI reduction over time
- evidence quality versus decision outcomes
- time spent resolving decision debt
- recurring evidence gaps by team
- which types of evidence most frequently change decisions
- whether organizations systematically decide with insufficient evidence

**None of these are implemented, stubbed or scheduled in the one-week MVP.** The MVP's versioned assessments, parameter versions and decision records are the only groundwork.

## 30. Scope Control and Change Log

**Principle:** the one-week constraint is primary. Anything that conflicts with it is future scope, not MVP expansion.

**Revision 2 complexity assessment**

| Addition | Added effort | Mitigation |
|---|---|---|
| Lifecycle (through Decided) | Low: one enum column, guard functions, audit entries | No new tables |
| Evidence Health | Low–Medium: one SQL view, one Power BI page | Reuses D1–D3, P1–P2 inputs. In-app table is "Should" |
| DDI transparency panel | Medium: one UI component | Data already produced by the DDI engine. Replaces what would have been a number badge |
| Decision Canvas | Low: one form, validation | Fields live on `decisions` |
| Positioning text | Trivial | Shared constant |
| Narrative / future analytics | Documentation only | |

**Day-3 reconciliation (2026-10-02).** Product Owner decisions R1-R14 and the Day-3 clarifications are recorded in [day-3-implementation-brief.md](day-3-implementation-brief.md) and [day-3-implementation-notes.md](day-3-implementation-notes.md): DDI meaning and the evidence-direction summary, cap reconciliation, band edge and rounding, quality-adjusted P1, normalized HHI, versioned and hashed parameters, assessment versioning and immutability, concurrency, human review and override, demo role switcher. No DDI dimension and no NBE action was added.

**Unchanged:** four agents (Orchestrator, Data & Analytics, Evidence Synthesis, Reviewer/Critic), seven UI stages, deterministic DDI, Power BI (Must), evaluation (Must), traceability matrix (Must), NBE (Must), INSUFFICIENT EVIDENCE as a first-class outcome, mandatory human decision, synthetic and labelled FitConnect data, the approved technology stack.

**Revised cut order (Power BI, evaluation, traceability, NBE, deterministic DDI and the transparency panel are never cut):** hosted demo → in-app Evidence Health table → PRD-lite generator → anomaly flag → UI polish → eval scenario count beyond the four core scenarios and a few variants.

**Estimated day impact:** Day 2 +0.25 (canvas columns, `v_evidence_health`). Day 3 +0.25 (lifecycle guards). Day 6 +0.5 (DDI panel, canvas form, Evidence Health Power BI page), absorbed by the existing buffer on Day 7. If this proves optimistic, cut per the order above.

---

## Product Owner Approval Checklist (revision 2)

- [ ] Decision Lifecycle approved (MVP stops at *Human Decision Recorded*; Outcome Observed / Re-assessment are future)
- [ ] Evidence Health approved (descriptive view only, no composite score, no new tables)
- [ ] DDI transparency approved (no bare number, ever)
- [ ] Decision Canvas approved (lightweight form on the decision object)
- [ ] DDI positioning approved ("transparent evidence-risk heuristic", maths unchanged)
- [ ] Four-agent architecture retained
- [ ] Seven-stage pipeline retained
- [ ] Power BI retained (Must)
- [ ] Synthetic FitConnect data retained (and always labelled)
- [ ] One-week scope retained

### Blocking decisions that still need Product Owner input

None block Day-1 *documentation* approval. Two environment facts must be confirmed **before the stage that depends on them**:

1. **Anthropic API access:** confirm you have an API key with Sonnet access, and whether Opus is available. This is needed before Day 4. (If Opus is unavailable, the Reviewer falls back to Sonnet and logs it, which is already decided.)
2. **Power BI Desktop:** confirm it is installed on this Windows machine. This is needed before Day 6. I will build the reporting views on Day 2 regardless.

**Parameter defaults** in DDI-spec (tier and grade factors, half-lives, penalty coefficients, band cutoffs, NBE effort bands and ceilings) are proposed v0.1 defaults. They are configurable and are **not blocking**. Approval of this document accepts them as the starting configuration.

*Nothing is implemented. Implementation starts only on the explicit phrase: "Approved. Start Day 1 implementation."*
