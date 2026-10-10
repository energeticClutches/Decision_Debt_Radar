Decision Debt Radar: Power BI data snapshot
Synthetic data. DDI is an evidence-risk heuristic, not a measure of decision quality.
FitConnect is a fictional company. Every row comes from synthetic data. Anything derived from an LLM stage is "stub, not model output":
syntheses and reviews in the demo are replayed hand-authored fixtures (models named stub:*), not live model output.

Files (written by scripts/export_reporting_views.py, read-only, deterministic for a given database state):
  v_debt_radar.csv, v_evidence_health.csv, v_evidence_freshness.csv, v_coverage_checklist.csv, v_nbe_ranking.csv,
  v_traceability_matrix.csv, v_agent_quality.csv   the seven reporting views of the database
  decisions_lifecycle.csv                          one row per decision: stage, stale flag, latest assessment state, band, as-of date
  eval_metrics.csv                                 evaluation metrics; NOT EVIDENCED rows are included and shown as such

Rules:
  - ddi_score is empty unless the assessment is scored. A decision with INSUFFICIENT EVIDENCE has no DDI value and no band.
  - ddi_score of a STALE assessment (assessment_stale = true) is shown as Stale in the report, never as a current number.
  - Arrays are joined with ';'. Booleans are true/false. Dates are ISO. Encoding is UTF-8 without a byte-order mark.
  - days_since_assessed (v_debt_radar) compares the assessment creation time with the as-of date and can be negative when a fixed
    demo as-of date precedes the run date; the report uses days_since_assessment from decisions_lifecycle.csv (as-of date minus the
    assessment's own as-of date).
