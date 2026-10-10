"""Compute the evaluation metrics and write the evaluation report (docs/day-7-implementation-brief.md section 2).

    PYTHONPATH="backend;." backend/.venv/Scripts/python scripts/eval_report.py            # read analytics/eval/results.json and mutation_results.json
    PYTHONPATH="backend;." backend/.venv/Scripts/python scripts/eval_report.py --run      # run the spec suite and the mutation suite first (rolled back)

Writes analytics/eval/metrics.json, docs/evaluation-report.md and docs/spot-audit.md. Read-only on the database.

Honesty rules: every figure is SYNTHETIC; no model was called. Reviewer recall and false-flag rate, real classification accuracy and live
schema validity are reported as NOT EVIDENCED. A figure derived from the keyword-rule stub says so ("stub, not model output").
"""

from __future__ import annotations

import argparse
import hashlib
import json
import re
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path[:0] = [str(ROOT / "backend"), str(ROOT), str(ROOT / "tests" / "evals")]

import eval_harness  # noqa: E402

eval_harness.setup_path()
import eval_runner as er  # noqa: E402
import mutations as mt  # noqa: E402

EVAL_DIR = ROOT / "analytics" / "eval"
REPORT = ROOT / "docs" / "evaluation-report.md"
SPOT = ROOT / "docs" / "spot-audit.md"
NOT_MEASURED = "not measured: no live model (replay fixtures are hand-authored)"
SYNTH = "Synthetic data"
STUB = "stub, not model output"
GOLDEN_TOLERANCE = 0.005


def pct(num: int, den: int) -> str:
    return "n/a" if not den else f"{100 * num / den:.1f}% ({num}/{den})"


# ---------------------------------------------------------------- inputs
def load_results() -> dict:
    return json.loads((EVAL_DIR / "results.json").read_text(encoding="utf-8"))


def load_mutation_results() -> dict:
    return json.loads((EVAL_DIR / "mutation_results.json").read_text(encoding="utf-8"))


def run_suites() -> None:
    specs = er.load_specs()
    results = []
    for spec in specs:
        with eval_harness.rolled_back_session() as (session, seed):
            results.append(er.run_spec(session, seed, spec))
    er.write_results(results, specs)
    from day5_support import Scenario
    with eval_harness.rolled_back_session() as (session, seed):
        scenarios = {name: Scenario(session, seed, name).run() for name in mt.SCENARIOS}
        payloads = {name: sc.evidence_input()[0] for name, sc in scenarios.items()}
        mt.write_results(mt.run_suite(payloads, scenarios["ai_coach"].ctx.ddi_params.design_rank))


# ---------------------------------------------------------------- database-backed metrics
def _engine():
    from sqlalchemy import create_engine
    return create_engine(eval_harness._database_url(), future=True)


def manifest_values() -> dict[str, float]:
    import psycopg

    from app.db.csv_loader import to_conninfo
    from database.seed.run import database_url
    from database.seed.validate import run_checks
    manifest = json.loads((ROOT / "data" / "generated" / "manifest.json").read_text(encoding="utf-8"))
    with psycopg.connect(to_conninfo(database_url())) as conn:
        conn.execute("SET TIME ZONE 'UTC'")
        return {r["id"]: r["value"] for r in run_checks(conn, manifest)}


def golden_answers(results: dict, mvals: dict[str, float]) -> list[dict]:
    """Stored analysis values (Day-4 analytics, from the demo path) against the manifest's SQL-derived values, within a tolerance."""
    by = {s["spec"]: s["extras"].get("analysis_values", {}) for s in results["specs"]}
    ai, com, pr = by.get("core_ai_coach", {}), by.get("core_community", {}), by.get("core_pricing", {})
    rows = [
        ("AI Coach: adopters minus non-adopters, D90 retention (comparison effect)", "AI-001", ai.get("comparison_effect")),
        ("AI Coach: experiment treatment share (observed allocation)", "AI-006", (ai.get("experiment", {}).get("observed_allocation") or {}).get("ai_coach")),
        ("AI Coach: experiment enrolled share of planned sample", "AI-008",
         None if not ai.get("experiment") else ai["experiment"]["n"] / ai["experiment"]["planned_sample"]),
        ("Community: joiners minus non-joiners, D90 retention (comparison effect)", "COM-001", com.get("comparison_effect")),
        ("Community: segment social_exerciser effect", "COM-002", (com.get("segment_effects") or {}).get("social_exerciser")),
        ("Community: segment solo_athlete effect", "COM-003", (com.get("segment_effects") or {}).get("solo_athlete")),
        ("Community: segment time_pressed effect", "COM-004", (com.get("segment_effects") or {}).get("time_pressed")),
        ("Pricing: CA pilot trial-to-paid change (comparison effect)", "PRC-003", pr.get("comparison_effect")),
        ("Pricing: experiment enrolled share of planned sample", "PRC-008",
         None if not pr.get("experiment") else pr["experiment"]["n"] / pr["experiment"]["planned_sample"]),
    ]
    out = []
    for label, check, got in rows:
        want = mvals.get(check)
        ok = got is not None and want is not None and abs(got - want) <= GOLDEN_TOLERANCE
        out.append({"quantity": label, "manifest_check": check, "manifest_value": want, "analysis_value": None if got is None else round(got, 4),
                    "abs_diff": None if got is None or want is None else round(abs(got - want), 4), "within_tolerance": ok})
    flag = com.get("heterogeneity_flag")
    out.append({"quantity": "Community: heterogeneity flag (manifest: True)", "manifest_check": "COM-002..004 (expected_downstream)",
                "manifest_value": True, "analysis_value": flag, "abs_diff": None, "within_tolerance": flag is True})
    flag = ai.get("heterogeneity_flag")
    out.append({"quantity": "AI Coach: heterogeneity flag (Day-4 expected: False)", "manifest_check": "day-4 expected vs observed",
                "manifest_value": False, "analysis_value": flag, "abs_diff": None, "within_tolerance": flag is False})
    return out


def dq_recall(results: dict) -> dict:
    manifest = json.loads((ROOT / "data" / "generated" / "manifest.json").read_text(encoding="utf-8"))
    defects = manifest["scenarios"]["onboarding"]["defects"]
    spec = next(s for s in results["specs"] if s["spec"] == "core_onboarding")
    checks = spec["observed_detail"]["dq"]
    rows = []
    for d in defects:
        target = f"{d['event_name']}@{d['platform']}"
        hit = [c for c in checks if c["target"] == target and c["status"] == "open"]
        rows.append({"defect": d["id"], "target": target, "detected": bool(hit),
                     "checks": [f"{c['check_type']} ({c['severity']})" for c in hit]})
    return {"defects": rows, "detected": sum(1 for r in rows if r["detected"]), "total": len(rows)}


def sql_guard_pass_rate() -> dict:
    proc = subprocess.run([sys.executable, "-m", "pytest", "tests/backend/test_day4_sql_guard.py", "-q", "-p", "no:cacheprovider"],
                          cwd=ROOT, capture_output=True, text=True, timeout=900)
    text = proc.stdout + proc.stderr
    passed = int((re.search(r"(\d+) passed", text) or [0, 0])[1])
    failed = int((re.search(r"(\d+) failed", text) or [0, 0])[1])
    return {"passed": passed, "failed": failed, "total": passed + failed, "file": "tests/backend/test_day4_sql_guard.py"}


def classification_accuracy() -> dict:
    """The keyword-rule STUB against the evaluation-only ground truth. Not a model. Reads the ground-truth table, which product code never reads."""
    from sqlalchemy.orm import Session
    from stub_classifier import classify_text
    from test_day5_evals import GROUND_TRUTH_LABEL, SCENARIOS, ground_truth_rows, per_theme_scores
    eng = _engine()
    with Session(eng) as session:                  # the evaluation-only labels are read through the test helper, never by product code
        rows = ground_truth_rows(session)
    eng.dispose()
    scores = per_theme_scores(rows, lambda body, scenario, themes: classify_text(body, themes)[0])
    return {"rows": len(rows), "distinct_texts": len({b for _, b, _ in rows}), "scenarios": list(SCENARIOS),
            "themes": {k: {"precision": round(v[0], 4), "recall": round(v[1], 4), "tp": v[2], "predicted": v[3], "actual": v[4]}
                       for k, v in scores.items()}, "label": GROUND_TRUTH_LABEL}


def product_kpis() -> dict:
    """PRD section 17 product KPIs from the DEMO database (synthetic; syntheses and reviews there are replayed fixtures)."""
    from sqlalchemy import text as sql
    eng = _engine()
    with eng.connect() as c:
        n_dec = c.execute(sql("select count(*) from decisions")).scalar()
        assessed = c.execute(sql("select count(distinct decision_id) from decision_assessments where state in ('scored','insufficient_evidence')")).scalar()
        latest = c.execute(sql("select a.state, a.ddi_band from decisions d join lateral (select x.* from decision_assessments x "
                               "where x.decision_id = d.id order by x.version desc limit 1) a on true")).all()
        all_assess = c.execute(sql("select count(*) filter (where state='insufficient_evidence'), count(*) filter (where state in ('scored','insufficient_evidence')) "
                                   "from decision_assessments")).one()
        recs = c.execute(sql("select count(*) filter (where status='accepted'), count(*) filter (where status in ('accepted','rejected')) from recommendations")).one()
        decided = c.execute(sql("select count(*), count(*) filter (where r.acknowledged_risk) from decision_records r where r.outcome <> 'defer'")).one()
        risky = c.execute(sql("select count(*) from decision_records r join lateral (select x.* from decision_assessments x where x.decision_id = r.decision_id "
                              "order by x.version desc limit 1) a on true where r.outcome <> 'defer' and (a.state <> 'scored' or a.ddi_band in ('high','critical'))")).scalar()
        claims = c.execute(sql("select count(*) from claims")).scalar()
        resolved = c.execute(sql(
            "select count(*) from claims c where exists (select 1 from claim_evidence ce join evidence e on e.id = ce.evidence_id "
            "join evidence_sources s on s.id = e.evidence_source_id where ce.claim_id = c.id)")).scalar()
        quant = c.execute(sql(
            "select count(*) filter (where exists (select 1 from claim_evidence ce join evidence e on e.id = ce.evidence_id "
            "where ce.claim_id = c.id and e.analysis_id is not null)), count(*) from claims c where exists (select 1 from claim_evidence ce "
            "join evidence e on e.id = ce.evidence_id where ce.claim_id = c.id and e.evidence_type in ('behavioral','experiment') "
            "and e.created_by <> 'user')")).one()
    eng.dispose()
    return {"decisions": n_dec, "with_completed_assessment": assessed, "latest_states": [list(r) for r in latest],
            "insufficient_assessments": all_assess[0], "completed_assessments": all_assess[1],
            "nbe_accepted": recs[0], "nbe_decided": recs[1], "decided_records": decided[0], "decided_with_ack": decided[1],
            "decided_while_high_or_insufficient": risky, "claims": claims, "claims_with_evidence_and_source": resolved,
            "quant_claims_with_analysis": quant[0], "quant_claims": quant[1]}


def parameter_versions() -> list[dict]:
    rows = []
    reg = json.loads((ROOT / "backend" / "config" / "params_hashes.json").read_text(encoding="utf-8"))
    for k, v in reg.items():
        rows.append({"kind": "engine parameters", "version": k, "file": v["file"], "sha256": v["sha256"]})
    reg = json.loads((ROOT / "backend" / "config" / "orgs" / "config_hashes.json").read_text(encoding="utf-8"))
    for k, v in reg.items():
        rows.append({"kind": "tenant configuration", "version": k, "file": v["file"], "sha256": v["sha256"]})
    reg = json.loads((ROOT / "prompts" / "prompt_hashes.json").read_text(encoding="utf-8"))
    for ver, prompts in reg.items():
        for name, v in prompts.items():
            rows.append({"kind": "prompt", "version": f"{ver}/{name}", "file": v["file"], "sha256": v["sha256"]})
    for path in sorted((ROOT / "tests" / "evals" / "scenarios").glob("*.yaml")) + [ROOT / "tests" / "evals" / "mutations.yaml",
                                                                                   ROOT / "tests" / "evals" / "golden" / "observed.json"]:
        rows.append({"kind": "evaluation input", "version": path.name, "file": str(path.relative_to(ROOT)).replace("\\", "/"),
                     "sha256": hashlib.sha256(path.read_bytes().replace(b"\r\n", b"\n")).hexdigest()})
    return rows


# ---------------------------------------------------------------- metrics
def compute(results: dict, mres: dict, *, database: bool = True) -> dict:
    specs = results["specs"]
    metrics: dict = {"label": f"{SYNTH}. No model was called. Figures from stubs say '{STUB}'.", "synthetic": True}
    # DDI reproducibility
    repro = [s for s in specs if s.get("reproducible") is not None]
    metrics["ddi_reproducibility"] = {"value": f"{sum(1 for s in repro if s['reproducible'])}/{len(repro)}", "target": "100%",
                                      "met": all(s["reproducible"] for s in repro) and bool(repro),
                                      "method": "the frozen engine run twice on the stored facts of each spec; payloads compared"}
    eq = [s for s in specs if s.get("stored_equals_recomputed") is not None]
    metrics["stored_equals_recomputed"] = {"value": f"{sum(1 for s in eq if s['stored_equals_recomputed'])}/{len(eq)}"}
    # expected-state match
    def state_ok(s):
        return next((c["ok"] for c in s["checks"] if c["name"] == "state"), None)
    core = [s for s in specs if s["group"] == "core"]
    var = [s for s in specs if s["group"] == "variant"]
    metrics["expected_state_match"] = {
        "core": f"{sum(1 for s in core if state_ok(s))}/{len(core)}", "variants": f"{sum(1 for s in var if state_ok(s))}/{len(var)}",
        "target": "100% core", "met": all(state_ok(s) for s in core)}
    metrics["spec_pass"] = {g: f"{sum(1 for s in specs if s['group'] == g and s['pass'])}/{sum(1 for s in specs if s['group'] == g)}"
                            for g in ("core", "variant", "extra")}
    metrics["known_gaps"] = [{"spec": s["spec"], "check": c["name"], "reason": " ".join((c["known_gap"] or "").split())}
                             for s in specs for c in s["checks"] if c.get("known_gap")]
    metrics["unexpected_failures"] = [{"spec": s["spec"], "check": c["name"]} for s in specs for c in s["checks"]
                                      if not c["ok"] and not c.get("known_gap")]
    # citation validity
    tot = sum(s["extras"].get("claims_total", 0) for s in specs)
    dropped = sum(s["extras"].get("claims_dropped_v_id", 0) for s in specs)
    stored = sum(s["extras"].get("claims_stored", 0) for s in specs)
    stored_ok = sum(s["extras"].get("claims_stored_with_valid_ids", 0) for s in specs)
    ms = mres["summary"]
    metrics["citation_validity"] = {
        "specs_before_filter": pct(tot - dropped, tot), "specs_after_filter": pct(stored_ok, stored),
        "mutations_before_filter": pct(ms["citation_valid_before_filter"], ms["claims_total"]),
        "mutations_after_filter": pct(ms["citation_valid_after_filter"], ms["claims_surviving"]),
        "target": "post-filter 100%", "met": stored_ok == stored and ms["citation_valid_after_filter"] == ms["claims_surviving"]}
    # code-check recall
    metrics["code_check"] = {"flaw_types": ms["flaw_types"], "instances": ms["instances"], "caught": ms["caught"], "recall": ms["recall"],
                             "controls": ms["controls"], "controls_flagged": ms["controls_flagged"], "false_flag_rate": ms["false_flag_rate"],
                             "target": "report; no target set",
                             "misses": [f"{i['id']} {i['flaw']} ({i['scenario']})" for i in mres["instances"] if i["applicable"] and not i["caught"]]}
    metrics["reviewer_recall_and_false_flags"] = {"status": "NOT EVIDENCED", "reason": NOT_MEASURED}
    metrics["live_schema_validity"] = {"status": "NOT EVIDENCED", "reason": NOT_MEASURED}
    if database:
        sg = sql_guard_pass_rate()
        metrics["sql_guard_pass_rate"] = {"value": pct(sg["passed"], sg["total"]), "target": "100%", "met": sg["failed"] == 0 and sg["total"] > 0,
                                          "method": "the existing guard test corpus (no LLM SQL by design), renamed from 'SQL validity'",
                                          "file": sg["file"]}
        metrics["dq_seeded_defect_recall"] = dict(dq_recall(results), target=">= 90%")
        metrics["dq_seeded_defect_recall"]["met"] = metrics["dq_seeded_defect_recall"]["detected"] / metrics["dq_seeded_defect_recall"]["total"] >= 0.9
        metrics["golden_answer_accuracy"] = {"rows": golden_answers(results, manifest_values()), "tolerance": GOLDEN_TOLERANCE, "target": "report"}
        g = metrics["golden_answer_accuracy"]["rows"]
        metrics["golden_answer_accuracy"]["value"] = f"{sum(1 for r in g if r['within_tolerance'])}/{len(g)}"
        ca = classification_accuracy()
        metrics["classification_accuracy"] = dict(ca, status="MEASURED on the keyword-rule stub only", label=STUB,
                                                  real_model="NOT EVIDENCED: " + NOT_MEASURED)
        metrics["product_kpis"] = dict(product_kpis(), label="demo data (synthetic); syntheses and reviews are replayed hand-authored fixtures")
        metrics["parameter_versions"] = parameter_versions()
    return metrics


# ---------------------------------------------------------------- the report
def md_table(headers: list[str], rows: list[list]) -> str:
    out = ["| " + " | ".join(headers) + " |", "|" + "|".join("---" for _ in headers) + "|"]
    for r in rows:
        out.append("| " + " | ".join(str(c).replace("|", "\\|").replace("\n", " ") for c in r) + " |")
    return "\n".join(out)


def manifest_band_comparison(golden: dict) -> list[list]:
    manifest = json.loads((ROOT / "data" / "generated" / "manifest.json").read_text(encoding="utf-8"))
    rows = []
    for scen, spec_id in (("ai_coach", "core_ai_coach"), ("community", "core_community"), ("onboarding", "core_onboarding"), ("pricing", "core_pricing")):
        exp = manifest["scenarios"][scen]["expected_downstream"]
        snap = golden["specs"][spec_id]
        want = exp.get("ddi_band")
        got = snap["band"]
        if want is None:
            verdict = "match (no band expected)" if got is None else "MISMATCH"
        else:
            verdict = "within the expected set" if got in want else "OUTSIDE the expected set"
        rows.append([scen, exp["assessment_state"], snap["state"], ", ".join(want) if want else "none", got or "none (INSUFFICIENT)", verdict])
    return rows


def write_report(metrics: dict, results: dict, mres: dict) -> None:
    golden = er.load_golden()
    specs = results["specs"]
    m = metrics
    L: list[str] = []
    A = L.append
    A("# Evaluation report (Day 7)\n")
    A(f"> **{SYNTH}.** FitConnect is a fictional company. Anything derived from an LLM stage is **{STUB}**. "
      "DDI is an evidence-risk heuristic, not a measure of decision quality.\n")
    A("## 1. Scope and honesty statement\n")
    A("This report evaluates the **deterministic** parts of Decision Debt Radar and the **plumbing** around the LLM boundary: the frozen DDI and NBE "
      "engines, the validators, the deterministic critic checks, the lifecycle and permission rules, the data-quality checks, the analytics against the "
      "seed manifest, and the human gate on customer evidence.\n")
    A("**No live model was called, ever.** No API key exists. The classification, synthesis and review in every run are *replayed*: a keyword-rule stub "
      "and hand-authored fixtures, each marked `stub_not_model_output`. Therefore this report **does not measure any model behaviour**. The following "
      f"are **NOT EVIDENCED** ({NOT_MEASURED}):\n")
    A("- Reviewer recall of seeded flaws and the Reviewer's false-flag rate (PRD target: recall >= 80%, <= 20% false flags);")
    A("- real classification accuracy (the stub's score below says nothing about a model);")
    A("- live schema validity and repair-retry rate of a real model;")
    A("- prompt-injection resistance and refusal correctness of a real model (here a *scripted* compromised output is shown to be rejected by code).\n")
    A("A criterion that is not evidenced is reported as NOT EVIDENCED, never made to pass. Nothing in `backend/demo_fixtures/` or `tests/fixtures/llm/` "
      "was edited to make a result pass.\n")
    A("## 2. Method\n")
    A(f"- **Specs.** {len(specs)} declarative scenarios in `tests/evals/scenarios/*.yaml` (4 core, 6 PRD section 19 variants, {sum(1 for s in specs if s['group'] == 'extra')} extra), "
      "each marked `synthetic: true`. A spec names a base scenario, a list of **mutations** applied through the real API (services), and what it expects: state, "
      "blocking reasons (an exact set), a band **or** no DDI, NBE actions, code findings, lifecycle stage and named properties.")
    A("- **No band is chosen in advance (D7-01).** A spec states `band: golden`. The engine's observed output is recorded in `tests/evals/golden/observed.json` "
      "by `scripts/eval_snapshot.py --write` (never by hand). Every run checks that the stored result equals `assess(facts)` recomputed on the stored facts **and** "
      "equals the snapshot (drift detection).")
    A("- **Isolation.** Every spec runs inside a pytest transaction on the seeded database and is rolled back; the demo database is never written "
      "(a test compares row counts before and after). Mutations never use raw SQL on product tables, with two documented test-only exceptions: the Day-5 E3 injected "
      "insight row, and the approval-bypass *attempt* (a statement the database must refuse, run in a rolled-back savepoint).")
    A("- **Code-layer mutation suite.** 22 flaw families (`tests/evals/mutations.yaml`) are seeded into valid syntheses built from the real input payloads of the four "
      "scenarios; each records the validator rule or critic category that must catch it. Valid syntheses of the four scenarios are the clean controls.")
    A("- **Clock.** The as-of date is fixed (2026-10-01) except in the stale-evidence variant, which moves it forward on purpose.\n")
    A("## 3. Results\n")
    A("### 3.1 Metrics against the PRD section 17/19 targets\n")
    rows = [
        ["DDI reproducibility", m["ddi_reproducibility"]["value"], "100%", "MET" if m["ddi_reproducibility"]["met"] else "NOT MET"],
        ["Stored result equals recomputed engine", m["stored_equals_recomputed"]["value"], "100%",
         "MET" if m["stored_equals_recomputed"]["value"].split("/")[0] == m["stored_equals_recomputed"]["value"].split("/")[1] else "NOT MET"],
        ["Expected-state match, core", m["expected_state_match"]["core"], "100%", "MET" if m["expected_state_match"]["met"] else "NOT MET"],
        ["Expected-state match, variants", m["expected_state_match"]["variants"], "report", "reported"],
        ["Citation validity before filtering (specs)", m["citation_validity"]["specs_before_filter"], "report", "reported"],
        ["Citation validity after filtering (specs)", m["citation_validity"]["specs_after_filter"], "100%", "MET" if m["citation_validity"]["met"] else "NOT MET"],
        ["Citation validity before / after filtering (mutation suite)",
         f"{m['citation_validity']['mutations_before_filter']} / {m['citation_validity']['mutations_after_filter']}", "after 100%", "MET" if m["citation_validity"]["met"] else "NOT MET"],
        ["SQL-guard pass rate (existing guard corpus; no LLM SQL by design)", m["sql_guard_pass_rate"]["value"], "100%", "MET" if m["sql_guard_pass_rate"]["met"] else "NOT MET"],
        ["Data-quality seeded-defect recall", f"{m['dq_seeded_defect_recall']['detected']}/{m['dq_seeded_defect_recall']['total']}", ">= 90%",
         "MET" if m["dq_seeded_defect_recall"]["met"] else "NOT MET"],
        ["Golden-answer accuracy (analyses vs manifest, tolerance 0.005)", m["golden_answer_accuracy"]["value"], "report", "reported"],
        ["Code-check recall (validators and deterministic critic)", f"{m['code_check']['caught']}/{m['code_check']['instances']} ({m['code_check']['recall']:.1%})", "report; no target set", "reported"],
        ["Code-check false-flag rate (clean controls)", f"{m['code_check']['controls_flagged']}/{m['code_check']['controls']}", "report; no target set", "reported"],
        ["Reviewer recall and false flags", "NOT EVIDENCED", ">= 80% / <= 20%", NOT_MEASURED],
        [f"Classification accuracy ({STUB})", "see 3.5", "report", "stub only; real model " + NOT_MEASURED],
    ]
    A(md_table(["Metric", "Result", "Target", "Status"], rows) + "\n")
    A("### 3.2 Specs\n")
    A(f"Full spec pass (every expectation met): core {m['spec_pass']['core']}, variants {m['spec_pass']['variant']}, extra {m['spec_pass']['extra']}. "
      "Expected-state match is the `state` expectation only (a spec with a documented known gap still matches its state).\n")
    A(md_table(["Spec", "Group", "Expected", "Observed", "Pass"],
               [[s["spec"], s["group"], s["expected"], s["observed"], "yes" if s["pass"] else "NO"] for s in specs]) + "\n")
    A("The full per-check detail is in `analytics/eval/results.json`; the flat table is `analytics/eval/results.csv`.\n")
    A("### 3.3 Golden bands (observed frozen-engine output, D7-01)\n")
    A("These bands are the engine's output recorded in the snapshot. They were not chosen in advance and are not judged right or wrong here.\n")
    A(md_table(["Spec", "State", "DDI", "Band", "NBE rank 1"],
               [[k, v["state"], "no DDI" if v["ddi"] is None else v["ddi"], v["band"] or "none", v["nbe_rank1"] or ""]
                for k, v in golden["specs"].items()]) + "\n")
    A("**The manifest's expected bands, for comparison (informational).** `data/generated/manifest.json` lists an expected DDI band set for each scenario:\n")
    A(md_table(["Scenario", "Manifest expects state", "Observed state", "Manifest expects band", "Observed band", "Verdict"], manifest_band_comparison(golden)) + "\n")
    A("### 3.4 Data quality and golden answers\n")
    dq = m["dq_seeded_defect_recall"]
    A(md_table(["Seeded defect", "Target", "Detected (open check)", "Checks"],
               [[d["defect"], d["target"], "yes" if d["detected"] else "NO", "; ".join(d["checks"])] for d in dq["defects"]]) + "\n")
    g = m["golden_answer_accuracy"]
    A(md_table(["Quantity", "Manifest check", "Manifest value", "Analysis value", "Abs. diff", "Within 0.005"],
               [[r["quantity"], r["manifest_check"], r["manifest_value"], r["analysis_value"], r["abs_diff"], "yes" if r["within_tolerance"] else "NO"]
                for r in g["rows"]]) + "\n")
    A("### 3.5 Classification (the keyword-rule stub, not a model)\n")
    ca = m["classification_accuracy"]
    A(f"**{STUB}.** The classifier here is a deterministic keyword-rule stub whose cues were written while the generator's template sentences were visible. "
      f"The synthetic feedback is **templated**: {ca['distinct_texts']} distinct sentences for {ca['rows']:,} rows. Near-perfect agreement therefore measures the pipeline "
      "and the stub, and says nothing about real customer text or a real model. **Real classification accuracy: NOT EVIDENCED** "
      f"({NOT_MEASURED}).\n")
    A(md_table(["Theme", "Precision", "Recall", "True positives", "Predicted", "Actual"],
               [[t, v["precision"], v["recall"], v["tp"], v["predicted"], v["actual"]] for t, v in ca["themes"].items()]) + "\n")
    A("### 3.6 Code-layer mutation suite\n")
    cc = m["code_check"]
    A(f"{cc['flaw_types']} flaw families, {cc['instances']} seeded instances: **{cc['caught']} caught ({cc['recall']:.1%})**. Clean controls flagged: "
      f"{cc['controls_flagged']} of {cc['controls']}. This measures the validators and the deterministic critic checks only. "
      "A Reviewer *model* was not involved.\n")
    by_fam: dict = {}
    for i in mres["instances"]:
        if i["applicable"]:
            f = by_fam.setdefault(i["id"], {"flaw": i["flaw"], "layer": i["layer"], "rule": i["must_be_caught_by"], "n": 0, "caught": 0})
            f["n"] += 1
            f["caught"] += 1 if i["caught"] else 0
    A(md_table(["Id", "Flaw", "Must be caught by", "Caught"],
               [[k, f["flaw"], f"{f['layer']}: {f['rule']}", f"{f['caught']}/{f['n']}"] for k, f in by_fam.items()]) + "\n")
    A("### 3.7 Product KPIs (PRD section 17), demo data\n")
    k = m["product_kpis"]
    A(f"*Labelled demo data (synthetic). Syntheses and reviews in the demo database are replayed fixtures ({STUB}).*\n")
    if k["decisions"] and k["with_completed_assessment"]:
        A(md_table(["KPI", "Value", "Note"], [
            ["Assessment coverage", pct(k["with_completed_assessment"], k["decisions"]), "decisions with >= 1 completed assessment"],
            ["Insufficient-evidence rate", pct(k["insufficient_assessments"], k["completed_assessments"]), "of all stored completed assessment versions, superseded ones included (monitored, not minimised)"],
            ["Acknowledged-risk decisions", f"{k['decided_while_high_or_insufficient']} decided while High/Critical/insufficient; {k['decided_with_ack']} of {k['decided_records']} records acknowledge risk",
             "the demo state has no decided decision unless a Playwright run advanced one"],
            ["Traceability rate", pct(k["claims_with_evidence_and_source"], k["claims"]), "claims with >= 1 evidence id and one source"],
            ["Quantitative claims with an analysis", pct(k["quant_claims_with_analysis"], k["quant_claims"]), "behavioral/experiment claims whose cited evidence has an analysis id"],
            ["NBE acceptance rate", pct(k["nbe_accepted"], k["nbe_decided"]), "no recommendation has been accepted or rejected in the demo state"],
            ["Time-to-assessment vs a manual baseline", "not measured", "no manual baseline exists"],
            ["Observed DDI reduction after an accepted NBE action", "not measured", "no accepted NBE action has been followed by a re-assessment"],
        ]) + "\n")
    else:
        A("The demo database holds no completed assessment (run `scripts/demo_prepare.py` first); the KPIs are therefore not computed in this run.\n")
    A("## 4. Failures and not-evidenced items\n")
    if m["known_gaps"]:
        A("**Known gaps (a documented expectation that the frozen engines do not meet; the spec records it as a failure, nothing was tuned):**\n")
        for gp in m["known_gaps"]:
            A(f"- `{gp['spec']}` / `{gp['check']}`: {gp['reason']}")
        A("")
    if m["unexpected_failures"]:
        A("**Unexpected failures:** " + ", ".join(f"{u['spec']}/{u['check']}" for u in m["unexpected_failures"]) + "\n")
    else:
        A("No unexpected failure: every expectation of every spec is met except the known gaps above.\n")
    A("**Found and fixed by the evaluation (D7-06).** Before the V-NUM sign check, the seeded wrong-sign flaw (M13: a claim saying the outcome *decreased* by the "
      "exact magnitude of a positive effect) was **missed in 3 of 3 instances** (code-check recall 58/61 = 95.1%). After the sign check all 61 are caught, "
      "the clean controls are still not flagged, and the Day-5 fixtures still pass.\n")
    A("**Community band vs manifest.** The manifest expects a *moderate* band for Community; the frozen engine returns *high*. The snapshot records the engine output "
      "(D7-01); the manifest's band set was a Day-1 expectation, not a validated target. It is reported, not tuned.\n")
    A("**NOT EVIDENCED** (" + NOT_MEASURED + "): reviewer recall, reviewer false-flag rate, real classification accuracy, live schema validity, repair-retry rate, "
      "real-model injection resistance, real-model refusal correctness, time-to-assessment against a manual baseline.\n")
    A("## 5. The stub and templated-data caveats\n")
    A(f"- Every classification, synthesis and review in this report is a **replayed fixture or a keyword-rule stub ({STUB})**. The hand-authored synthesis and review "
      "fixtures deliberately contain injected flaws (a causal overclaim for AI Coach, a \"no harm\" claim for Pricing) so the pipeline can be exercised; the Reviewer "
      "that flags them is a fixture, not evidence that a model would.")
    A(f"- The synthetic customer feedback is templated ({ca['distinct_texts']} distinct sentences for {ca['rows']:,} rows). Any agreement with the generator's labels is optimistic by construction.")
    A("- FitConnect data is synthetic and generated from a fixed seed; segment effects, defects and experiment shapes were authored to exercise the engines.")
    A("- The DDI v0.1 parameters are *proposed defaults*, not validated. The golden bands are what the engine returns for these synthetic inputs, not a claim about the real world.")
    A("- The clean controls and mutated syntheses are built by code from real payloads; they are not human- or model-written text, so the false-flag rate of the code layers on real model output is unknown.\n")
    A("## 6. How to reproduce\n")
    A("```bash\ndocker compose up -d db\nPYTHONPATH=\"backend;.\" backend/.venv/Scripts/python -m database.seed.run --reset      # clean synthetic data\n"
      "PYTHONPATH=\"backend;.\" DDR_LLM_MODE=replay backend/.venv/Scripts/python scripts/demo_prepare.py       # demo state (KPIs and the spot-audit read it)\n"
      "backend/.venv/Scripts/python -m pytest tests/evals                                                    # specs + mutation suite, rolled back; writes analytics/eval/*\n"
      "PYTHONPATH=\"backend;.\" backend/.venv/Scripts/python scripts/eval_snapshot.py --check                 # engine output vs the golden snapshot\n"
      "PYTHONPATH=\"backend;.\" backend/.venv/Scripts/python scripts/eval_report.py                           # metrics.json, this report, the spot-audit sheet\n```")
    A("To re-record the golden snapshot after a deliberate, approved engine change: `scripts/eval_snapshot.py --write` (never edit the file by hand).\n")
    A("## 7. Versions and hashes of every parameter set and prompt\n")
    A(md_table(["Kind", "Version / name", "File", "SHA-256"], [[r["kind"], r["version"], r["file"], f"`{r['sha256']}`"] for r in m["parameter_versions"]]) + "\n")
    REPORT.write_text("\n".join(L) + "\n", encoding="utf-8", newline="\n")


# ---------------------------------------------------------------- the spot-audit sheet
def write_spot_audit() -> bool:
    """For each core scenario: 5 sampled stored claims and every finding, with BLANK PO columns. The implementer never fills them."""
    from sqlalchemy import text as sql
    eng = _engine()
    out = ["# Human spot-audit sheet (PRD section 19, layer 6)\n",
           f"> **{SYNTH}.** The claims and findings below were produced by **replayed fixtures** ({STUB}), stored by the demo path. "
           "The Product Owner fills the `agrees` and `note` columns. The implementer never does.\n",
           "How to read it: a claim *agrees* if its text is a fair statement of the cited evidence; a finding *agrees* if the flag is justified. Sampling is "
           "deterministic: the five claims with the smallest SHA-256 of `scenario:claim id`.\n"]
    wrote = False
    with eng.connect() as c:
        for scen, title in (("ai_coach", "Invest in expanding the AI Coach"), ("community", "Invest in community challenges"),
                            ("onboarding", "Fund a full onboarding redesign"), ("pricing", "Raise the premium subscription price")):
            row = c.execute(sql("select d.id, a.id, a.version, a.state from decisions d join lateral (select x.* from decision_assessments x "
                                "where x.decision_id = d.id order by x.version desc limit 1) a on true where d.title = :t"), {"t": title}).first()
            out.append(f"\n## {scen.replace('_', ' ').title()}\n")
            if row is None:
                out.append("_No assessment in the database: run `scripts/demo_prepare.py`._\n")
                continue
            claims = c.execute(sql("select cl.id::text, cl.claim_text, cl.claim_type, cl.stance::text, cl.confidence, cl.conclusion_ref from claims cl "
                                   "where cl.assessment_id = :a"), {"a": row[1]}).all()
            sample = sorted(claims, key=lambda r: hashlib.sha256(f"{scen}:{r[0]}".encode()).hexdigest())[:5]
            out.append(f"Assessment v{row[2]} ({row[3]}). {len(claims)} stored claims; 5 sampled.\n")
            out.append(md_table(["#", "Claim (stored)", "Type", "Stance", "Confidence", "Ref", "agrees", "note"],
                                [[i + 1, r[1], r[2], r[3], r[4], r[5] or "", "", ""] for i, r in enumerate(sample)]) + "\n")
            findings = c.execute(sql("select r.reviewer_type, r.verdict, f.value ->> 'category', f.value ->> 'severity', f.value ->> 'source', "
                                     "f.value ->> 'rationale' from decision_reviews r cross join lateral jsonb_array_elements(r.challenges) f(value) "
                                     "where r.assessment_id = :a order by r.created_at, f.value ->> 'category'"), {"a": row[1]}).all()
            out.append("Every finding of the stored review(s):\n")
            out.append(md_table(["#", "Reviewer", "Category", "Severity", "Source", "Rationale", "agrees", "note"],
                                [[i + 1, r[0], r[2], r[3], r[4], r[5] or "", "", ""] for i, r in enumerate(findings)]) + "\n" if findings
                       else "_No findings stored._\n")
            wrote = wrote or bool(claims)
    eng.dispose()
    SPOT.write_text("\n".join(out) + "\n", encoding="utf-8", newline="\n")
    return wrote


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--run", action="store_true", help="run the spec suite and the mutation suite first (rolled back)")
    ap.add_argument("--no-database", action="store_true")
    args = ap.parse_args()
    if args.run:
        run_suites()
    results, mres = load_results(), load_mutation_results()
    metrics = compute(results, mres, database=not args.no_database)
    (EVAL_DIR / "metrics.json").write_text(json.dumps(metrics, indent=2, ensure_ascii=False, default=str) + "\n", encoding="utf-8", newline="\n")
    if not args.no_database:
        write_report(metrics, results, mres)
        wrote = write_spot_audit()
        print(f"wrote {REPORT.relative_to(ROOT)}, {SPOT.relative_to(ROOT)} (claims sampled: {wrote}) and analytics/eval/metrics.json")
    else:
        print("wrote analytics/eval/metrics.json (database-backed metrics skipped)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
