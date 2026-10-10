"""Write the Power BI project (PBIP) as TEXT: a TMDL semantic model and a PBIR report definition (docs/day-7-implementation-brief.md section 4).

    backend/.venv/Scripts/python scripts/build_pbip.py [--data-folder <absolute path>]

Output (deterministic; UTF-8 without BOM, LF):
    analytics/powerbi/DecisionDebtRadar.pbip
    analytics/powerbi/DecisionDebtRadar.SemanticModel/   definition.pbism + definition/ (TMDL: model, expressions, relationships, tables)
    analytics/powerbi/DecisionDebtRadar.Report/          definition.pbir + definition/ (PBIR: report, version, pages, visuals)
    analytics/powerbi/visuals-spec.md                    the same pages, visuals, fields, measures and labels, in prose

The model reads the CSVs written by scripts/export_reporting_views.py through the `DataFolder` parameter. The report definition uses the
PBIR format with the schema versions bundled with Power BI Desktop 2.158 (report 3.3.0, page 2.1.0, visualContainer 2.13.0, pages
metadata 1.1.0, version 1.0.0). Neither the TMDL nor the PBIR was opened in Power BI Desktop by the implementer: see analytics/powerbi/README.md.

Rules built into the model: no DDI value for an insufficient decision (the average DDI measure counts scored, current assessments only; the
band label of an insufficient or stale decision is text, never a number); a neutral single-colour scale with text labels; every page footer
carries "Synthetic data · DDI is an evidence-risk heuristic, not a measure of decision quality".
"""

from __future__ import annotations

import argparse
import csv
import json
import uuid
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
PBI = ROOT / "analytics" / "powerbi"
DATA = PBI / "data"
NAME = "DecisionDebtRadar"
NS = uuid.UUID("5d1e8a4e-0b7a-4f3a-9c55-0d0ec1510001")
FOOTER = "Synthetic data · DDI is an evidence-risk heuristic, not a measure of decision quality"
STUB_NOTE = "Figures marked 'stub, not model output' come from replayed fixtures and keyword rules, not a live model. NOT EVIDENCED means not measured: no live model (replay fixtures are hand-authored)."
DEFAULT_DATA_FOLDER = str(DATA).replace("/", "\\")

SCHEMA = "https://developer.microsoft.com/json-schemas/fabric"
S_REPORT = f"{SCHEMA}/item/report/definition/report/3.3.0/schema.json"
S_PAGE = f"{SCHEMA}/item/report/definition/page/2.1.0/schema.json"
S_VISUAL = f"{SCHEMA}/item/report/definition/visualContainer/2.13.0/schema.json"
S_PAGES = f"{SCHEMA}/item/report/definition/pagesMetadata/1.1.0/schema.json"
S_VERSION = f"{SCHEMA}/item/report/definition/versionMetadata/1.0.0/schema.json"
S_PBIR = f"{SCHEMA}/item/report/definitionProperties/2.0.0/schema.json"
S_PBIP = f"{SCHEMA}/pbip/pbipProperties/1.0.0/schema.json"


def tag(*parts) -> str:
    return str(uuid.uuid5(NS, "/".join(str(p) for p in parts)))


# ====================================================================== the model
# M type per column; anything not listed stays text. DAX data type follows the M type.
TYPES = {
    "v_debt_radar": {"assessment_stale": "bool", "assessment_version": "int", "ddi_score": "num", "band_stable": "bool", "days_since_assessed": "int",
                     "decision_due_date": "date", "is_synthetic": "bool"},
    "v_evidence_health": {"value": "num", "as_of_date": "date", "is_synthetic": "bool"},
    "v_evidence_freshness": {"observed_end": "date", "age_days": "int", "half_life_days": "int", "within_half_life": "bool", "reliability_tier": "int",
                             "days_since_source_load": "int", "is_synthetic": "bool"},
    "v_coverage_checklist": {"is_synthetic": "bool"},
    "v_nbe_ranking": {"assessment_version": "int", "is_superseded": "bool", "effort_days": "num", "expected_reduction": "num", "relevance": "num",
                      "priority_score": "num", "rank_in_assessment": "int", "is_synthetic": "bool"},
    "v_traceability_matrix": {"assessment_version": "int", "reliability_tier": "int", "is_synthetic": "bool"},
    "v_agent_quality": {"runs": "int", "succeeded": "int", "failed": "int", "partial": "int", "runs_with_error": "int", "avg_latency_ms": "num",
                        "tokens_in": "int", "tokens_out": "int", "claims_dropped": "int", "is_synthetic": "bool"},
    "decisions_lifecycle": {"assessment_stale": "bool", "latest_assessment_version": "int", "assessment_as_of_date": "date", "days_since_assessment": "int",
                            "report_as_of_date": "date", "open_critical_dq_issues": "int", "open_warn_dq_issues": "int", "is_synthetic": "bool"},
    "eval_metrics": {"stub_not_model_output": "bool", "is_synthetic": "bool"},
}
M_TYPE = {"int": "Int64.Type", "num": "type number", "bool": "type logical", "date": "type date"}
DAX_TYPE = {"text": "string", "int": "int64", "num": "double", "bool": "boolean", "date": "dateTime"}
TABLE_ORDER = ["decisions_lifecycle", "v_debt_radar", "v_evidence_health", "v_evidence_freshness", "v_coverage_checklist", "v_nbe_ranking",
               "v_traceability_matrix", "v_agent_quality", "eval_metrics"]

# Optional live mode (D7-03): the seven reporting views can be read from PostgreSQL through a login role that is a member of ddr_readonly
# (DataSource = "postgres"). It is NOT the default and is not exercised by the tests. decisions_lifecycle and eval_metrics always come from CSV.
VIEW_TABLES = ["v_debt_radar", "v_evidence_health", "v_evidence_freshness", "v_coverage_checklist", "v_nbe_ranking", "v_traceability_matrix", "v_agent_quality"]
ENUM_COLUMNS = {"risk_level", "lifecycle_stage", "assessment_state", "ddi_band", "evidence_type", "stage", "status"}
ARRAY_COLUMNS = {"accepted_types": "array_to_string(accepted_types::text[], ';')", "dimensions_addressed": "array_to_string(dimensions_addressed::text[], ';')",
                 "reviewer_challenge_ids": "array_to_string(reviewer_challenge_ids, ';')"}


def live_sql(table: str, cols: list[str]) -> str:
    parts = []
    for c in cols:
        if c in ARRAY_COLUMNS:
            parts.append(f"{ARRAY_COLUMNS[c]} AS {c}")
        elif c in ENUM_COLUMNS:
            parts.append(f"{c}::text AS {c}")
        elif c == "is_synthetic" and table == "v_coverage_checklist":
            parts.append("true AS is_synthetic")
        else:
            parts.append(c)
    return f"SELECT {', '.join(parts)} FROM {table}"


# calculated columns: (table, name, dax, dataType)
CALC_COLUMNS = [
    ("decisions_lifecycle", "band_label",
     'SWITCH(TRUE(), decisions_lifecycle[assessment_stale] = TRUE(), "Stale (not current)", decisions_lifecycle[latest_assessment_state] = "insufficient_evidence", '
     '"INSUFFICIENT EVIDENCE (no DDI)", decisions_lifecycle[latest_assessment_state] = "scored", UPPER(LEFT(decisions_lifecycle[ddi_band], 1)) '
     '& MID(decisions_lifecycle[ddi_band], 2, 20) & " band", "No assessment")', "string"),
    ("decisions_lifecycle", "decided_at_risk",
     'AND(decisions_lifecycle[lifecycle_stage] = "decided", OR(decisions_lifecycle[latest_assessment_state] <> "scored", '
     'decisions_lifecycle[ddi_band] = "high", decisions_lifecycle[ddi_band] = "critical"))', "boolean"),
    ("v_evidence_freshness", "age_bucket",
     'SWITCH(TRUE(), v_evidence_freshness[age_days] <= 30, "0-30 days", v_evidence_freshness[age_days] <= 90, "31-90 days", '
     'v_evidence_freshness[age_days] <= 180, "91-180 days", "Over 180 days")', "string"),
    ("v_nbe_ranking", "reduction_label",
     'IF(RELATED(decisions_lifecycle[latest_assessment_state]) = "scored", FORMAT(v_nbe_ranking[expected_reduction], "0.0") '
     '& " DDI points (potential, not a prediction)", "Resolves blockers (no DDI)")', "string"),
    ("v_agent_quality", "provenance_label",
     'IF(LEFT(v_agent_quality[model], 5) = "stub:", "stub, not model output", IF(ISBLANK(v_agent_quality[model]), "deterministic stage (no model)", "model output"))',
     "string"),
    ("eval_metrics", "provenance_label",
     'IF(eval_metrics[status] = "NOT EVIDENCED", "not measured: no live model", IF(eval_metrics[stub_not_model_output] = TRUE(), "stub, not model output", "deterministic"))',
     "string"),
]

# measures: (table, name, dax, formatString or None)
MEASURES = [
    ("decisions_lifecycle", "Decisions", "COUNTROWS(decisions_lifecycle)", "0"),
    ("decisions_lifecycle", "Scored decisions", 'CALCULATE(COUNTROWS(decisions_lifecycle), decisions_lifecycle[latest_assessment_state] = "scored")', "0"),
    ("decisions_lifecycle", "Insufficient decisions",
     'CALCULATE(COUNTROWS(decisions_lifecycle), decisions_lifecycle[latest_assessment_state] = "insufficient_evidence")', "0"),
    ("decisions_lifecycle", "Stale decisions", "CALCULATE(COUNTROWS(decisions_lifecycle), decisions_lifecycle[assessment_stale] = TRUE())", "0"),
    ("decisions_lifecycle", "Average DDI (scored, current)",
     'CALCULATE(AVERAGE(v_debt_radar[ddi_score]), v_debt_radar[assessment_state] = "scored", v_debt_radar[assessment_stale] = FALSE())', "0.0"),
    ("decisions_lifecycle", "Open critical DQ issues", "SUM(decisions_lifecycle[open_critical_dq_issues])", "0"),
    ("decisions_lifecycle", "Open warn DQ issues", "SUM(decisions_lifecycle[open_warn_dq_issues])", "0"),
    ("decisions_lifecycle", "Decided while High, Critical or insufficient",
     "CALCULATE(COUNTROWS(decisions_lifecycle), decisions_lifecycle[decided_at_risk] = TRUE())", "0"),
    ("decisions_lifecycle", "Days since last assessment", "MAX(decisions_lifecycle[days_since_assessment])", "0"),
    ("v_evidence_freshness", "Evidence items", "COUNTROWS(v_evidence_freshness)", "0"),
    ("v_evidence_freshness", "Share within half-life",
     "DIVIDE(CALCULATE(COUNTROWS(v_evidence_freshness), v_evidence_freshness[within_half_life] = TRUE()), COUNTROWS(v_evidence_freshness))", "0%"),
    ("eval_metrics", "Not evidenced metrics", 'CALCULATE(COUNTROWS(eval_metrics), eval_metrics[status] = "NOT EVIDENCED")', "0"),
    ("eval_metrics", "Measured metrics", 'CALCULATE(COUNTROWS(eval_metrics), eval_metrics[status] <> "NOT EVIDENCED")', "0"),
]

CALC_TABLES = {
    "Teams": ('DISTINCT(SELECTCOLUMNS(decisions_lifecycle, "team_id", decisions_lifecycle[team_id], "team", decisions_lifecycle[team]))', ["team_id", "team"]),
    "DecisionTypes": ('DISTINCT(SELECTCOLUMNS(decisions_lifecycle, "decision_type", decisions_lifecycle[decision_type]))', ["decision_type"]),
}

RELATIONSHIPS = [
    ("v_debt_radar", "decision_id", "decisions_lifecycle", "decision_id"),
    ("v_evidence_freshness", "decision_id", "decisions_lifecycle", "decision_id"),
    ("v_nbe_ranking", "decision_id", "decisions_lifecycle", "decision_id"),
    ("v_traceability_matrix", "decision_id", "decisions_lifecycle", "decision_id"),
    ("decisions_lifecycle", "team_id", "Teams", "team_id"),
    ("decisions_lifecycle", "decision_type", "DecisionTypes", "decision_type"),
    ("v_evidence_health", "team_id", "Teams", "team_id"),
    ("v_evidence_health", "decision_type", "DecisionTypes", "decision_type"),
    ("v_coverage_checklist", "decision_type", "DecisionTypes", "decision_type"),
]


def q(name: str) -> str:
    """A TMDL identifier: quoted when it has anything but letters, digits and underscore."""
    return name if name.replace("_", "").isalnum() else "'" + name.replace("'", "''") + "'"


def csv_columns(table: str) -> list[str]:
    with (DATA / f"{table}.csv").open(encoding="utf-8", newline="") as fh:
        return next(csv.reader(fh))


def table_tmdl(table: str) -> str:
    cols = csv_columns(table)
    types = TYPES[table]
    L = [f"table {q(table)}", f"\tlineageTag: {tag('table', table)}", ""]
    for name, dax, fmt in [(m[1], m[2], m[3]) for m in MEASURES if m[0] == table]:
        L.append(f"\tmeasure {q(name)} = {dax}")
        if fmt:
            L.append(f"\t\tformatString: {fmt}")
        L.append(f"\t\tlineageTag: {tag('measure', table, name)}")
        L.append("")
    for c in cols:
        kind = types.get(c, "text")
        L.append(f"\tcolumn {q(c)}")
        L.append(f"\t\tdataType: {DAX_TYPE[kind]}")
        if kind == "date":
            L.append("\t\tformatString: Long Date")
        L.append(f"\t\tlineageTag: {tag('column', table, c)}")
        L.append("\t\tsummarizeBy: none")
        L.append(f"\t\tsourceColumn: {c}")
        L.append("")
    for t, name, dax, dtype in CALC_COLUMNS:
        if t != table:
            continue
        L.append(f"\tcolumn {q(name)} = {dax}")
        L.append(f"\t\tdataType: {dtype}")
        L.append(f"\t\tlineageTag: {tag('column', table, name)}")
        L.append("\t\tsummarizeBy: none")
        L.append("")
    typed = ", ".join(f'{{"{c}", {M_TYPE[types[c]]}}}' for c in cols if c in types)
    csv_step = f'Csv.Document(File.Contents(DataFolder & "\\{table}.csv"), [Delimiter = ",", Columns = {len(cols)}, Encoding = 65001, QuoteStyle = QuoteStyle.Csv])'
    ind = "\t\t\t\t"
    M = [ind + "let", ind + f"    Raw = {csv_step},",
         ind + "    Promoted = Table.PromoteHeaders(Raw, [PromoteAllScalars = true]),",
         ind + '    Clean = Table.ReplaceValue(Promoted, "", null, Replacer.ReplaceValue, Table.ColumnNames(Promoted)),']
    if table in VIEW_TABLES:
        M += [ind + f'    Live = PostgreSQL.Database(PgServer, PgDatabase, [Query = "{live_sql(table, cols)}"]),',
              ind + '    Chosen = if DataSource = "postgres" then Live else Clean,']
    else:
        M += [ind + "    Chosen = Clean,"]
    M += [ind + f'    Typed = Table.TransformColumnTypes(Chosen, {{{typed}}}, "en-US")', ind + "in", ind + "    Typed"]
    L += [f"\tpartition {q(table)} = m", "\t\tmode: import", "\t\tsource ="] + M + ["", "\tannotation PBI_ResultType = Table", ""]
    return "\n".join(L)


def calc_table_tmdl(name: str) -> str:
    dax, cols = CALC_TABLES[name]
    L = [f"table {q(name)}", f"\tlineageTag: {tag('table', name)}", ""]
    for c in cols:
        L += [f"\tcolumn {q(c)}", "\t\tdataType: string", f"\t\tlineageTag: {tag('column', name, c)}", "\t\tsummarizeBy: none", f"\t\tsourceColumn: [{c}]", ""]
    L += [f"\tpartition {q(name)} = calculated", "\t\tmode: import", f"\t\tsource = {dax}", "", "\tannotation PBI_Id = " + tag("calc", name).replace("-", ""), ""]
    return "\n".join(L)


def semantic_model(data_folder: str) -> dict[str, str]:
    base = f"{NAME}.SemanticModel"
    files: dict[str, str] = {}
    files[f"{base}/definition.pbism"] = json.dumps({"version": "4.0", "settings": {}}, indent=2) + "\n"
    files[f"{base}/definition/database.tmdl"] = f"database {NAME}\n\tcompatibilityLevel: 1600\n"
    refs = "\n".join(f"ref table {q(t)}" for t in TABLE_ORDER + list(CALC_TABLES))
    files[f"{base}/definition/model.tmdl"] = (
        "model Model\n\tculture: en-US\n\tdefaultPowerBIDataSourceVersion: powerBI_V3\n\tsourceQueryCulture: en-US\n\tdiscourageImplicitMeasures\n"
        "\tdataAccessOptions\n\t\tlegacyRedirects\n\t\treturnErrorValuesAsNull\n\n" + refs
        + "\n\nref expression DataFolder\nref expression DataSource\nref expression PgServer\nref expression PgDatabase\n")

    def param(name, value, doc):
        return (f'/// {doc}\nexpression {name} = "{value}" meta [IsParameterQuery = true, IsParameterQueryRequired = true, Type = "Text"]\n'
                f"\tlineageTag: {tag('expression', name)}\n\tqueryGroup: Parameters\n\n\tannotation PBI_ResultType = Text\n")
    files[f"{base}/definition/expressions.tmdl"] = "\n".join([
        param("DataFolder", data_folder, "Absolute path of the folder with the CSV snapshot (analytics/powerbi/data). Change it on another machine."),
        param("DataSource", "csv", "csv (default) reads the CSV snapshot. postgres reads the seven reporting views live (optional, documented, not the default)."),
        param("PgServer", "127.0.0.1:5432", "PostgreSQL host and port for the optional live mode. Use 127.0.0.1, not localhost."),
        param("PgDatabase", "ddr", "PostgreSQL database for the optional live mode.")])
    rel = []
    for i, (ft, fc, tt, tc) in enumerate(RELATIONSHIPS, start=1):
        rel.append(f"relationship {tag('relationship', i)}\n\tfromColumn: {q(ft)}.{q(fc)}\n\ttoColumn: {q(tt)}.{q(tc)}\n")
    files[f"{base}/definition/relationships.tmdl"] = "\n".join(rel)
    for t in TABLE_ORDER:
        files[f"{base}/definition/tables/{t}.tmdl"] = table_tmdl(t)
    for t in CALC_TABLES:
        files[f"{base}/definition/tables/{t}.tmdl"] = calc_table_tmdl(t)
    return files


# ====================================================================== the report (PBIR)
def lit(value) -> dict:
    return {"expr": {"Literal": {"Value": value}}}


def s(text: str) -> dict:
    return lit("'" + text.replace("'", "''") + "'")


def col(table: str, prop: str) -> dict:
    return {"Column": {"Expression": {"SourceRef": {"Entity": table}}, "Property": prop}}


def meas(table: str, prop: str) -> dict:
    return {"Measure": {"Expression": {"SourceRef": {"Entity": table}}, "Property": prop}}


def proj(field: dict) -> dict:
    kind = "Column" if "Column" in field else "Measure"
    table, prop = field[kind]["Expression"]["SourceRef"]["Entity"], field[kind]["Property"]
    return {"field": field, "queryRef": f"{table}.{prop}", "nativeQueryRef": prop}


NEUTRAL = "#4B6584"


class Visual:
    def __init__(self, vid, vtype, x, y, w, h, title=None, roles=None, text=None, filters=None, alt=None, bold=False, size="10pt", labels=False):
        self.vid, self.vtype, self.x, self.y, self.w, self.h = vid, vtype, x, y, w, h
        self.title, self.roles, self.text, self.filters, self.alt = title, roles or {}, text, filters or [], alt
        self.bold, self.size, self.labels = bold, size, labels

    def fields_desc(self) -> str:
        parts = []
        for role, fields in self.roles.items():
            parts.append(f"{role}: " + ", ".join(f"{(f.get('Column') or f.get('Measure'))['Expression']['SourceRef']['Entity']}[{(f.get('Column') or f.get('Measure'))['Property']}]" for f in fields))
        return "; ".join(parts)

    def json(self, z: int) -> dict:
        v: dict = {"visualType": self.vtype}
        if self.vtype == "textbox":
            v["objects"] = {"general": [{"properties": {"paragraphs": [{"textRuns": [{"value": self.text, "textStyle": {
                "fontSize": self.size, **({"fontWeight": "bold"} if self.bold else {})}}], "horizontalTextAlignment": "left"}]}}]}
        else:
            v["query"] = {"queryState": {role: {"projections": [proj(f) for f in fields]} for role, fields in self.roles.items()}}
            objects = {}
            if self.vtype in ("clusteredBarChart", "clusteredColumnChart"):
                objects["dataPoint"] = [{"properties": {"fill": {"solid": {"color": lit(f"'{NEUTRAL}'")}}}}]
            if self.labels:
                objects["labels"] = [{"properties": {"show": lit("true")}}]
            if objects:
                v["objects"] = objects
        container = {}
        if self.title:
            container["title"] = [{"properties": {"show": lit("true"), "text": s(self.title)}}]
        if self.alt:
            container["general"] = [{"properties": {"altText": s(self.alt)}}]
        if container:
            v["visualContainerObjects"] = container
        v["drillFilterOtherVisuals"] = True
        out = {"$schema": S_VISUAL, "name": self.vid,
               "position": {"x": self.x, "y": self.y, "z": z, "height": self.h, "width": self.w, "tabOrder": z}, "visual": v}
        if self.filters:
            out["filterConfig"] = {"filters": self.filters}
        return out


def cat_filter(name: str, table: str, prop: str, values: list[str]) -> dict:
    src = "t"
    return {"name": name, "field": col(table, prop), "type": "Categorical",
            "filter": {"Version": 2, "From": [{"Name": src, "Entity": table, "Type": 0}],
                       "Where": [{"Condition": {"In": {"Expressions": [{"Column": {"Expression": {"SourceRef": {"Source": src}}, "Property": prop}}],
                                                       "Values": [[{"Literal": {"Value": v}}] for v in values]}}}]}}


def page_visuals(key: str) -> tuple[str, str, list[Visual]]:
    DL, DR = "decisions_lifecycle", "v_debt_radar"
    title = lambda pid, text: Visual(f"{pid}_title", "textbox", 16, 8, 1248, 44, text=text, bold=True, size="20pt")
    footer = lambda pid: Visual(f"{pid}_footer", "textbox", 16, 684, 1248, 28, text=FOOTER, size="10pt")
    slicers = lambda pid: [Visual(f"{pid}_team", "slicer", 16, 56, 300, 64, title="Team", roles={"Values": [col("Teams", "team")]}, alt="Filter by team"),
                           Visual(f"{pid}_type", "slicer", 330, 56, 330, 64, title="Decision type", roles={"Values": [col("DecisionTypes", "decision_type")]},
                                  alt="Filter by decision type")]
    if key == "p1":
        cards = [("Decisions", "Decisions"), ("Scored decisions", "Scored"), ("Insufficient decisions", "Insufficient evidence"),
                 ("Stale decisions", "Stale"), ("Average DDI (scored, current)", "Average DDI (scored, current decisions only)"),
                 ("Open critical DQ issues", "Open critical data-quality issues")]
        vis = [title("p1", "Portfolio debt · FitConnect (synthetic data)")] + slicers("p1")
        for i, (m, t) in enumerate(cards):
            vis.append(Visual(f"p1_card{i + 1}", "card", 16 + i * 208, 128, 200, 88, title=t, roles={"Values": [meas(DL, m)]}, alt=t))
        vis += [
            Visual("p1_bands", "clusteredBarChart", 16, 228, 420, 228, title="Decisions by DDI band (text labels; insufficient and stale are not bands)",
                   roles={"Category": [col(DL, "band_label")], "Y": [meas(DL, "Decisions")]}, labels=True, alt="Count of decisions per band label"),
            Visual("p1_team", "clusteredBarChart", 448, 228, 400, 228, title="Average DDI by team (scored, current only)",
                   roles={"Category": [col(DR, "team_name")], "Y": [meas(DL, "Average DDI (scored, current)")]}, labels=True,
                   alt="Average DDI per team, scored and current assessments only"),
            Visual("p1_type_bar", "clusteredBarChart", 860, 228, 404, 228, title="Average DDI by decision type (scored, current only)",
                   roles={"Category": [col(DR, "decision_type")], "Y": [meas(DL, "Average DDI (scored, current)")]}, labels=True,
                   alt="Average DDI per decision type, scored and current assessments only"),
            Visual("p1_risk", "tableEx", 16, 468, 1248, 208, title="Decided while High, Critical or insufficient (empty when none)",
                   roles={"Values": [col(DL, "title"), col(DL, "team"), col(DL, "lifecycle_stage"), col(DL, "band_label"), meas(DL, "Decided while High, Critical or insufficient")]},
                   filters=[cat_filter("filter_decided_at_risk", DL, "decided_at_risk", ["true"])], alt="Decisions recorded while High, Critical or insufficient"),
            footer("p1")]
        return "Portfolio debt", "p1", vis
    if key == "p2":
        FR = "v_evidence_freshness"
        vis = [title("p2", "Evidence health · FitConnect (synthetic data)")] + slicers("p2")
        vis += [
            Visual("p2_fresh", "clusteredColumnChart", 16, 128, 420, 230, title="Evidence freshness distribution (age of active evidence)",
                   roles={"Category": [col(FR, "age_bucket")], "Y": [meas(FR, "Evidence items")]}, labels=True, alt="Evidence items by age bucket"),
            Visual("p2_half", "clusteredBarChart", 448, 128, 400, 230, title="Share of evidence within its half-life, by evidence type",
                   roles={"Category": [col(FR, "evidence_type")], "Y": [meas(FR, "Share within half-life")]}, labels=True, alt="Share within half-life per evidence type"),
            Visual("p2_dq", "clusteredBarChart", 860, 128, 404, 230, title="Open data-quality issues by decision",
                   roles={"Category": [col(DL, "title")], "Y": [meas(DL, "Open critical DQ issues"), meas(DL, "Open warn DQ issues")]},
                   labels=True, alt="Open critical and warn data-quality issues per decision"),
            Visual("p2_health", "tableEx", 16, 370, 760, 306, title="Evidence health dimensions (no combined score)",
                   roles={"Values": [col("v_evidence_health", "decision_type"), col("v_evidence_health", "dimension"), col("v_evidence_health", "metric_name"),
                                     col("v_evidence_health", "value"), col("v_evidence_health", "indicator")]}, alt="Seven evidence-health dimensions by decision type"),
            Visual("p2_cover", "tableEx", 788, 370, 476, 150, title="Coverage checklist: required evidence by decision type",
                   roles={"Values": [col("v_coverage_checklist", "decision_type"), col("v_coverage_checklist", "required_label")]}, alt="Required evidence types"),
            Visual("p2_gaps", "tableEx", 788, 528, 476, 148, title="Open evidence gaps (latest assessments)",
                   roles={"Values": [col("v_traceability_matrix", "decision_title"), col("v_traceability_matrix", "claim_text")]},
                   filters=[cat_filter("filter_gap_rows", "v_traceability_matrix", "row_type", ["'gap'"])], alt="Missing required evidence per decision"),
            footer("p2")]
        return "Evidence health", "p2", vis
    if key == "p3":
        N = "v_nbe_ranking"
        vis = [title("p3", "Lifecycle and next best evidence · FitConnect (synthetic data)")] + slicers("p3")
        vis += [
            Visual("p3_stage", "clusteredBarChart", 16, 128, 380, 230, title="Decisions by lifecycle stage",
                   roles={"Category": [col(DL, "lifecycle_stage")], "Y": [meas(DL, "Decisions")]}, labels=True, alt="Count of decisions per lifecycle stage"),
            Visual("p3_table", "tableEx", 408, 128, 856, 230, title="Decisions: stage, assessment state and time since the last assessment",
                   roles={"Values": [col(DL, "title"), col(DL, "team"), col(DL, "lifecycle_stage"), col(DL, "band_label"), meas(DL, "Days since last assessment")]},
                   alt="Stage, state and age of the last assessment per decision"),
            Visual("p3_nbe", "tableEx", 16, 370, 1248, 306, title="Next Best Evidence ranking (current assessments; a potential reduction, not a prediction)",
                   roles={"Values": [col(N, "decision_title"), col(N, "rank_in_assessment"), col(N, "action_type"), col(N, "description"),
                                     col(N, "effort_days"), col(N, "reduction_label"), col(N, "priority_score")]},
                   filters=[cat_filter("filter_not_superseded", N, "is_superseded", ["false"])], alt="Ranked next best evidence actions"),
            footer("p3")]
        return "Lifecycle and NBE", "p3", vis
    EM, AQ = "eval_metrics", "v_agent_quality"
    vis = [title("p4", "Quality · evaluation and agent runs (synthetic data)"),
           Visual("p4_note", "textbox", 16, 56, 1248, 52, text=STUB_NOTE, size="11pt"),
           Visual("p4_c1", "card", 16, 116, 300, 88, title="Metrics measured", roles={"Values": [meas(EM, "Measured metrics")]}, alt="Count of measured metrics"),
           Visual("p4_c2", "card", 328, 116, 300, 88, title="Metrics NOT EVIDENCED (no live model)", roles={"Values": [meas(EM, "Not evidenced metrics")]},
                  alt="Count of metrics that are not evidenced"),
           Visual("p4_metrics", "tableEx", 16, 216, 1248, 270, title="Evaluation metrics (NOT EVIDENCED rows are shown as such)",
                  roles={"Values": [col(EM, "metric"), col(EM, "value"), col(EM, "target"), col(EM, "status"), col(EM, "provenance_label"), col(EM, "note")]},
                  alt="Evaluation metrics with status and provenance"),
           Visual("p4_agents", "tableEx", 16, 498, 1248, 178, title="Agent runs by stage and model (v_agent_quality)",
                  roles={"Values": [col(AQ, "agent_name"), col(AQ, "stage"), col(AQ, "model"), col(AQ, "provenance_label"), col(AQ, "prompt_version"),
                                    col(AQ, "runs"), col(AQ, "succeeded"), col(AQ, "failed"), col(AQ, "claims_dropped")]}, alt="Agent runs with provenance"),
           footer("p4")]
    return "Quality", "p4", vis


def page_name(key: str) -> str:
    return tag("page", key).replace("-", "")[:20]


def report_files() -> dict[str, str]:
    base = f"{NAME}.Report"
    files: dict[str, str] = {}
    j = lambda o: json.dumps(o, indent=2, ensure_ascii=False) + "\n"
    files[f"{base}/definition.pbir"] = j({"$schema": S_PBIR, "version": "4.0", "datasetReference": {"byPath": {"path": f"../{NAME}.SemanticModel"}}})
    files[f"{base}/definition/version.json"] = j({"$schema": S_VERSION, "version": "2.0.0"})
    files[f"{base}/definition/report.json"] = j({
        "$schema": S_REPORT, "themeCollection": {},
        "settings": {"useStylableVisualContainerHeader": True, "defaultDrillFilterOtherVisuals": True, "allowChangeFilterTypes": True,
                     "useEnhancedTooltips": True, "useDefaultAggregateDisplayName": True}})
    keys = ["p1", "p2", "p3", "p4"]
    files[f"{base}/definition/pages/pages.json"] = j({"$schema": S_PAGES, "pageOrder": [page_name(k) for k in keys], "activePageName": page_name(keys[0])})
    for k in keys:
        display, _, visuals = page_visuals(k)
        pname = page_name(k)
        files[f"{base}/definition/pages/{pname}/page.json"] = j({"$schema": S_PAGE, "name": pname, "displayName": display, "displayOption": "FitToPage",
                                                                  "height": 720, "width": 1280})
        for z, v in enumerate(visuals):
            files[f"{base}/definition/pages/{pname}/visuals/{v.vid}/visual.json"] = j(v.json(1000 + z))
    return files


def pbip_file() -> dict[str, str]:
    return {f"{NAME}.pbip": json.dumps({"$schema": S_PBIP, "version": "1.0", "artifacts": [{"report": {"path": f"{NAME}.Report"}}],
                                        "settings": {"enableAutoRecovery": True}}, indent=2) + "\n"}


def spec_md() -> str:
    L = ["# Power BI visuals specification (Day 7)\n",
         f"> **Synthetic data.** FitConnect is fictional. DDI is an evidence-risk heuristic, not a measure of decision quality. LLM-derived figures are "
         f"\"stub, not model output\". Generated by `scripts/build_pbip.py` from the same definitions that write the report; if the PBIP report definition "
         f"does not open in Power BI Desktop, build the visuals below by hand on the semantic model.\n",
         "Every page footer reads: **" + FOOTER + "**\n", "## Data and model\n",
         "Tables (CSV snapshot in `analytics/powerbi/data`, parameter `DataFolder`): " + ", ".join(f"`{t}`" for t in TABLE_ORDER) + ". Calculated tables: `Teams`, `DecisionTypes` "
         "(slicer sources). Relationships (many-to-one, single direction): " + "; ".join(f"`{a}[{b}]` -> `{c}[{d}]`" for a, b, c, d in RELATIONSHIPS) + ".\n",
         "### Measures\n", "| Measure | Table | DAX | Format |", "|---|---|---|---|"]
    for t, n, d, f in MEASURES:
        L.append(f"| {n} | {t} | `{d}` | {f} |")
    L += ["", "### Calculated columns\n", "| Column | Table | DAX |", "|---|---|---|"]
    for t, n, d, _ in CALC_COLUMNS:
        L.append(f"| {n} | {t} | `{d}` |")
    L += ["", "### Rules\n",
          "- **No DDI value for an insufficient decision:** `Average DDI (scored, current)` counts scored, non-stale assessments only; the band label of an insufficient or stale "
          "decision is the text `INSUFFICIENT EVIDENCE (no DDI)` or `Stale (not current)`; NBE `reduction_label` shows `Resolves blockers (no DDI)` for them.",
          f"- **Neutral colour:** one colour ({NEUTRAL}) for all bars; bands are text labels, no red/green verdict.",
          "- **Stale:** a stale assessment is counted by `Stale decisions` and labelled; its number is never part of the average.",
          "- **LLM-derived figures** carry `stub, not model output`; NOT EVIDENCED metrics are listed as such (page 4).\n"]
    for k in ("p1", "p2", "p3", "p4"):
        display, _, visuals = page_visuals(k)
        L += [f"## Page: {display}\n", "| Visual | Type | Position (x, y, w, h) | Title | Fields |", "|---|---|---|---|---|"]
        for v in visuals:
            body = v.text if v.vtype == "textbox" else v.fields_desc()
            flt = ""
            if v.filters:
                f0 = v.filters[0]
                flt = f" (filter {f0['field'].get('Column', {}).get('Property')} in {[x[0]['Literal']['Value'] for x in f0['filter']['Where'][0]['Condition']['In']['Values']]})"
            L.append(f"| {v.vid} | {v.vtype} | {v.x}, {v.y}, {v.w}, {v.h} | {v.title or ''} | {body}{flt} |")
        L.append("")
    return "\n".join(L) + "\n"


def write_all(data_folder: str) -> list[str]:
    files = {**pbip_file(), **semantic_model(data_folder), **report_files(), "visuals-spec.md": spec_md()}
    written = []
    for rel, body in files.items():
        path = PBI / rel
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(body, encoding="utf-8", newline="\n")
        written.append(rel)
    return written


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--data-folder", default=DEFAULT_DATA_FOLDER, help="absolute path of the CSV folder (the DataFolder parameter default)")
    args = ap.parse_args()
    if not DATA.exists() or not (DATA / "decisions_lifecycle.csv").exists():
        raise SystemExit("run scripts/export_reporting_views.py first")
    written = write_all(args.data_folder)
    print(f"wrote {len(written)} files under {PBI}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
