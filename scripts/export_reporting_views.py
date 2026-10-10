"""Export the reporting views to CSV for the Power BI report (docs/day-7-implementation-brief.md section 4, D7-03).

    PYTHONPATH="backend;." backend/.venv/Scripts/python scripts/export_reporting_views.py [--out analytics/powerbi/data] [--as-of 2026-10-01]

Writes, to analytics/powerbi/data/:
    v_debt_radar.csv v_evidence_health.csv v_evidence_freshness.csv v_coverage_checklist.csv v_nbe_ranking.csv
    v_traceability_matrix.csv v_agent_quality.csv   the seven reporting views, read through the read-only role (SET LOCAL ROLE ddr_readonly)
    decisions_lifecycle.csv                          title, team, type, stage, stale flag, latest assessment state, band, as-of date,
                                                     open critical and warn data-quality issue counts
    eval_metrics.csv                                 the evaluation metrics (analytics/eval/metrics.json), NOT EVIDENCED rows included
    README.txt                                       the label and the column notes (Power BI cannot skip a comment row, so no comment row)

Run it after `scripts/demo_prepare.py`. It is read-only and deterministic for a given database state: the as-of date is fixed (the views read
`ddr.as_of`), rows are sorted, no export timestamp is written, and CSVs are UTF-8 without a byte-order mark with LF line endings. Every CSV
has an `is_synthetic` column. A DDI number exists only for a scored assessment (the database guarantees it); a stale assessment is flagged.
"""

from __future__ import annotations

import argparse
import csv
import json
import os
import sys
from datetime import date, datetime, timezone
from decimal import Decimal
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path[:0] = [str(ROOT / "backend"), str(ROOT)]

DEFAULT_OUT = ROOT / "analytics" / "powerbi" / "data"
DEFAULT_AS_OF = "2026-10-01"
VIEWS = ("v_debt_radar", "v_evidence_health", "v_evidence_freshness", "v_coverage_checklist", "v_nbe_ranking",
         "v_traceability_matrix", "v_agent_quality")
LABEL = "Synthetic data. DDI is an evidence-risk heuristic, not a measure of decision quality."

README = f"""Decision Debt Radar: Power BI data snapshot
{LABEL}
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
"""


def fmt(v) -> str:
    if v is None:
        return ""
    if isinstance(v, bool):
        return "true" if v else "false"
    if isinstance(v, Decimal):
        return format(v.normalize(), "f")
    if isinstance(v, datetime):
        return v.astimezone(timezone.utc).isoformat().replace("+00:00", "Z")
    if isinstance(v, date):
        return v.isoformat()
    if isinstance(v, (list, tuple)):
        return ";".join(fmt(x) for x in v)
    if isinstance(v, dict):
        return json.dumps(v, sort_keys=True)
    return str(v)


def write_csv(path: Path, columns: list[str], rows: list[list]) -> int:
    body = sorted(([fmt(c) for c in r] for r in rows))
    with path.open("w", encoding="utf-8", newline="") as fh:
        w = csv.writer(fh, lineterminator="\n")
        w.writerow(columns)
        w.writerows(body)
    return len(body)


def eval_metric_rows(metrics_path: Path) -> list[list]:
    """Flat rows: metric, value, target, status, evidence label. Reviewer recall and false flags are always NOT EVIDENCED."""
    NE = "NOT EVIDENCED"
    rows: list[list] = []
    if metrics_path.exists():
        m = json.loads(metrics_path.read_text(encoding="utf-8"))
        def add(mid, name, value, target, status, stub=False, note=""):
            rows.append([mid, name, value, target, status, "true" if stub else "false", note, "true"])
        add("ddi_reproducibility", "DDI reproducibility", m["ddi_reproducibility"]["value"], "100%", "MEASURED")
        add("expected_state_core", "Expected-state match, core scenarios", m["expected_state_match"]["core"], "100%", "MEASURED")
        add("expected_state_variants", "Expected-state match, variants", m["expected_state_match"]["variants"], "report", "MEASURED")
        cv = m["citation_validity"]
        add("citation_validity_post", "Citation validity after filtering (specs)", cv["specs_after_filter"], "100%", "MEASURED")
        add("citation_validity_pre", "Citation validity before filtering (specs)", cv["specs_before_filter"], "report", "MEASURED")
        if "sql_guard_pass_rate" in m:
            add("sql_guard", "SQL-guard pass rate (guard test corpus)", m["sql_guard_pass_rate"]["value"], "100%", "MEASURED",
                note="no LLM-written SQL exists by design")
            d = m["dq_seeded_defect_recall"]
            add("dq_recall", "Data-quality seeded-defect recall", f"{d['detected']}/{d['total']}", ">= 90%", "MEASURED")
            add("golden_answers", "Golden-answer accuracy (analyses vs manifest)", m["golden_answer_accuracy"]["value"], "report", "MEASURED")
            ca = m["classification_accuracy"]
            lo = min(min(v["precision"], v["recall"]) for v in ca["themes"].values())
            add("classification_stub", "Classification precision and recall, minimum over themes", f"{lo:.3f}", "report",
                "MEASURED on a stub only", True, "stub, not model output; templated feedback; real model NOT EVIDENCED")
        cc = m["code_check"]
        add("code_check_recall", "Code-check recall (validators and deterministic critic)", f"{cc['caught']}/{cc['instances']}", "report; no target set", "MEASURED")
        add("code_check_false_flags", "Code-check false-flag rate (clean controls)", f"{cc['controls_flagged']}/{cc['controls']}", "report; no target set", "MEASURED")
    reason = "no live model (replay fixtures are hand-authored)"
    for mid, name, target in (("reviewer_recall", "Reviewer recall of seeded flaws", ">= 80%"),
                              ("reviewer_false_flags", "Reviewer false-flag rate", "<= 20%"),
                              ("classification_real", "Classification accuracy of a real model", "report"),
                              ("schema_validity_live", "Live schema validity", "report")):
        rows.append([mid, name, NE, target, NE, "false", "not measured: " + reason, "true"])
    return rows


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--out", default=str(DEFAULT_OUT))
    ap.add_argument("--as-of", default=os.environ.get("DDR_AS_OF_DATE") or DEFAULT_AS_OF)
    args = ap.parse_args()
    out = Path(args.out)
    out.mkdir(parents=True, exist_ok=True)
    as_of = date.fromisoformat(args.as_of)

    from sqlalchemy import create_engine, text

    from app.core.config import get_settings
    engine = create_engine(get_settings().database_url, future=True)
    written: dict[str, int] = {}
    with engine.connect() as conn:
        with conn.begin():
            conn.execute(text("SET TRANSACTION READ ONLY"))
            conn.execute(text("SET LOCAL TIME ZONE 'UTC'"))
            conn.execute(text("SELECT set_config('ddr.as_of', :d, true)"), {"d": as_of.isoformat()})
            conn.execute(text("SET LOCAL ROLE ddr_readonly"))         # the report sees only the reporting views
            for view in VIEWS:
                res = conn.execute(text(f"SELECT * FROM {view}"))
                cols = list(res.keys())
                rows = [list(r) for r in res]
                if "is_synthetic" not in cols:
                    cols.append("is_synthetic")
                    rows = [r + [True] for r in rows]
                written[view] = write_csv(out / f"{view}.csv", cols, rows)
            conn.execute(text("RESET ROLE"))
            res = conn.execute(text(
                "SELECT d.id AS decision_id, d.title, d.team_id, t.name AS team, d.decision_type, d.risk_level, d.lifecycle_stage, d.assessment_stale,"
                " a.version AS latest_assessment_version, a.state AS latest_assessment_state,"
                " CASE WHEN a.state = 'scored' THEN a.ddi_band END AS ddi_band, a.as_of_date AS assessment_as_of_date,"
                " CASE WHEN a.id IS NOT NULL THEN CAST(:asof AS date) - a.as_of_date END AS days_since_assessment,"
                " CAST(:asof AS date) AS report_as_of_date,"
                " (SELECT count(*) FROM dq_checks q WHERE q.decision_id = d.id AND q.status = 'open' AND q.severity = 'critical') AS open_critical_dq_issues,"
                " (SELECT count(*) FROM dq_checks q WHERE q.decision_id = d.id AND q.status = 'open' AND q.severity = 'warn') AS open_warn_dq_issues,"
                " d.is_synthetic"
                " FROM decisions d JOIN teams t ON t.id = d.team_id"
                " LEFT JOIN LATERAL (SELECT x.* FROM decision_assessments x WHERE x.decision_id = d.id ORDER BY x.version DESC LIMIT 1) a ON true"),
                {"asof": as_of.isoformat()})
            written["decisions_lifecycle"] = write_csv(out / "decisions_lifecycle.csv", list(res.keys()), [list(r) for r in res])
    engine.dispose()
    cols = ["metric_id", "metric", "value", "target", "status", "stub_not_model_output", "note", "is_synthetic"]
    written["eval_metrics"] = write_csv(out / "eval_metrics.csv", cols, eval_metric_rows(ROOT / "analytics" / "eval" / "metrics.json"))
    (out / "README.txt").write_text(README, encoding="utf-8", newline="\n")
    for name, n in written.items():
        print(f"{name + '.csv':<28} {n} rows")
    print(f"as-of {as_of.isoformat()}; wrote {out}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
