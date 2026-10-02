# Architecture Decision Records

**Status:** DRAFT v0.1 (Day-1 spec, pending Product Owner approval). Parent: [PRD-v0.1.md](PRD-v0.1.md) §21.
Format: Context → Decision → Consequences. All are *Accepted* in the Product Owner's PRD approval unless marked *Proposed (revision 2)*.

---

### ADR-001: Four agents, seven visible stages
**Context:** The goal is meaningful agentic architecture buildable in one week. **Decision:** Orchestrator, Data & Analytics, Evidence Synthesis, Reviewer/Critic. Customer-insight and experimentation are *capabilities* within Data & Analytics and Evidence Synthesis. The UI exposes seven stages (Data Quality, Quantitative Analysis, Customer Evidence, Experiment Evidence, Evidence Synthesis, Adversarial Review, Decision Brief). **Consequences:** Less orchestration complexity, and the user still sees a clear pipeline. No further agents are added.

### ADR-002: Plain Python orchestration, no agent framework
**Context:** The flow is linear with gates. **Decision:** Typed state machine in Python, Anthropic SDK tool use, Pydantic-validated outputs. **Consequences:** Transparent and easy to test. Fewer dependencies. We build retries and logging ourselves.

### ADR-003: Deterministic DDI, LLM never sets numbers
**Decision:** The DDI engine is pure Python with versioned parameters. The LLM classifies, summarizes and explains only (BR-5). **Consequences:** Reproducible, testable and auditable. Classification errors still influence inputs, mitigated by validation, the Reviewer and human edits.

### ADR-004: INSUFFICIENT EVIDENCE is a first-class outcome
**Decision:** Gating rules BR-1 to BR-4. `ddi_score` is NULL unless state is `scored` (DB check constraint). **Consequences:** Honest behavior and a strong demo (Onboarding scenario). Some decisions never get a number until evidence improves.

### ADR-005: Industry-agnostic core, `fc_` schema isolates demo data
**Decision:** The core schema and agents never reference FitConnect objects. Demo data enters through registered data sources and metrics. Checklists and parameters are configuration. **Consequences:** Portability. Slightly more indirection in the SQL guard and views.

### ADR-006: Read-only, allow-listed SQL with sqlglot validation
**Decision:** Generated SQL is parsed (SELECT only), checked against an allow-list of views, row-limited and time-limited, and executed with a read-only role. **Consequences:** Safe by construction. Analysis is limited to what the views expose.

### ADR-007: Claude only. Sonnet primary, Opus for the Reviewer where available
**Decision:** No other provider. If Opus is unavailable the Reviewer runs on Sonnet and the fallback is logged in `agent_runs`. **Consequences:** Single integration. Reviewer independence from the author is partly prompt-based when falling back.

### ADR-008: CSV-only ingestion, role-switcher instead of authentication
**Decision:** CSV loaders with schema validation. A role header and UI switcher enforce persona permissions server-side. **Consequences:** Fast to build. Explicitly not production security (stated in the README).

### ADR-009: Local-first, hosting optional
**Decision:** Docker Compose for local setup. Public hosting only if the core is stable. **Consequences:** Reliability over reach.

### ADR-010: Traceability matrix and Next Best Evidence are first-class modules
**Decision:** Claims, `claim_evidence`, `analysis_results` and the `v_traceability_matrix` view are core. NBE is computed by a deterministic engine using the DDI engine. **Consequences:** Added tables and views are justified by two Must-have capabilities.

### ADR-011: Power BI reads reporting views only *(Must)*
**Decision:** Power BI Desktop connects to `v_*` reporting views in PostgreSQL. Pages: Debt Radar, Evidence Health, Agent Quality. Business logic lives in SQL/engine, not in DAX. **Consequences:** One source of truth. Power BI cannot leak raw data. Requires Power BI Desktop availability.

### ADR-012: Decision lifecycle ends at "Human Decision Recorded" in the MVP *(Proposed, revision 2)*
**Context:** The long-term vision includes learning from outcomes, which needs outcome tracking. **Decision:** Implement stages 1–6 only, held in `decisions.lifecycle_stage` with transitions audit-logged. Outcome Observed and Re-assessment are documented as future. **Consequences:** No extra tables. Future work extends without re-modelling.

### ADR-013: Evidence Health is a descriptive view, not a score *(Proposed, revision 2)*
**Decision:** `v_evidence_health` reuses existing inputs and reports seven dimensions separately, with display indicators and no composite. **Consequences:** No competing metric, low effort, and it feeds a Power BI page.

### ADR-014: DDI is always displayed through the transparency panel *(Proposed, revision 2)*
**Decision:** The UI, brief, export and Power BI never show a bare number. They show breakdown, penalties, parameter version, sensitivity and Next Best Evidence. **Consequences:** One shared component. Reinforces the "evidence-risk heuristic" positioning.

### ADR-015: Decision Canvas is a form on the Decision object *(Proposed, revision 2)*
**Decision:** Canvas fields are columns on `decisions`. The canvas locks at first assessment and later edits are audit-logged. **Consequences:** Pre-commitment of criteria with minimal build cost. No separate entity.

### ADR-016: DDI positioning as an evidence-risk heuristic *(Proposed, revision 2)*
**Decision:** Documentation and UI state that DDI is a transparent evidence-risk heuristic, not a validated or predictive measure. The maths is unchanged and sensitivity analysis is a core safeguard. **Consequences:** Defensible in interviews. Avoids overclaiming.

### ADR-017: One-week constraint governs scope *(Proposed, revision 2)*
**Decision:** New requirements that conflict with the one-week limit become future scope. The cut order never removes Power BI, evaluation, traceability, NBE, deterministic DDI or the transparency panel. **Consequences:** Predictable delivery.
