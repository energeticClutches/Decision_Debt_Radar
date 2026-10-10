# Power BI report (Day 7)

> **Synthetic data.** FitConnect is a fictional company. DDI is an evidence-risk heuristic, not a measure of decision quality. LLM-derived figures are "stub, not model output".

## What is here

| Path | Purpose |
|---|---|
| `DecisionDebtRadar.pbip` | The project file. Open this in Power BI Desktop. |
| `DecisionDebtRadar.SemanticModel/` | TMDL semantic model: 9 CSV tables, 2 calculated tables (`Teams`, `DecisionTypes`), 9 relationships on `decision_id`, `team_id`, `decision_type`, measures and calculated columns. |
| `DecisionDebtRadar.Report/` | PBIR report definition, 4 pages: Portfolio debt, Evidence health, Lifecycle and NBE, Quality. |
| `data/` | CSV snapshot written by `scripts/export_reporting_views.py` (7 reporting views, `decisions_lifecycle.csv`, `eval_metrics.csv`, `README.txt`). |
| `visuals-spec.md` | Every page, visual, field, measure and label in prose (fallback if the report does not open). |

Everything except `data/` is written by `scripts/build_pbip.py` (`backend/.venv/Scripts/python scripts/build_pbip.py`). The CSVs are written by `scripts/export_reporting_views.py` after `scripts/demo_prepare.py`.

## Format and version

- Report: PBIR (folder format), schemas bundled with Power BI Desktop 2.158: report 3.3.0, page 2.1.0, visualContainer 2.13.0, pagesMetadata 1.1.0, version 1.0.0; `definition.pbir` version 4.0 with a `byPath` reference to the model.
- Model: TMDL (`definition.pbism` version 4.0, compatibility level 1600).
- **Validation done:** all 44 report JSON files validate (JSON Schema draft-07) against the schemas extracted from the installed Desktop 2.158. **Not done:** the project has not been opened in Desktop by the implementer. The TMDL syntax and the names of formatting objects (`labels`, `dataPoint`, text-box paragraphs) are written from knowledge and are unchecked. Expect to fix small things on first open.

## Open, refresh, save

1. Open `DecisionDebtRadar.pbip` in Power BI Desktop 2.158 or later.
2. Transform data > Edit parameters: set `DataFolder` to the absolute path of `analytics/powerbi/data` on this machine (the default is the path on the development machine). Keep `DataSource = csv`.
3. Refresh. Check every page and the footer label, then save as `DecisionDebtRadar.pbix`.

## Rules the report follows

- A DDI value never appears for an insufficient decision: `Average DDI (scored, current)` counts scored, non-stale assessments only; insufficient and stale decisions get the text labels `INSUFFICIENT EVIDENCE (no DDI)` and `Stale (not current)`.
- One neutral bar colour; bands are text labels, no red/green verdict.
- Every page footer: "Synthetic data · DDI is an evidence-risk heuristic, not a measure of decision quality".
- Page 4 lists NOT EVIDENCED metrics as such and marks stub-derived figures "stub, not model output".
- `days_since_assessed` in `v_debt_radar` can be negative with a fixed demo as-of date; the report uses `days_since_assessment` from `decisions_lifecycle.csv`.

## Optional live mode (not the default, not tested)

`DataSource = postgres` makes the seven view tables read PostgreSQL through `PgServer` and `PgDatabase`. `ddr_readonly` is a NOLOGIN role, so create a login role first, for example `CREATE ROLE ddr_report LOGIN PASSWORD '<local-only>' IN ROLE ddr_readonly;`, and use it in Desktop's credential prompt. Limits: the views then use the current date as their as-of date, and `decisions_lifecycle` and `eval_metrics` stay on CSV because `ddr_readonly` cannot read the decisions tables.
