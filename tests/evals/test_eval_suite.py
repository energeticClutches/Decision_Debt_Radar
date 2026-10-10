"""The Day-7 evaluation suite runner (docs/day-7-implementation-brief.md section 2).

One test per spec in tests/evals/scenarios/*.yaml, each on a rolled-back transaction (the demo database is never changed). The results are
written to analytics/eval/results.json and results.csv once every spec has run.

What a green result means here: the frozen deterministic engines, the validators, the lifecycle and the pipeline behave as each spec
states, and the stored results equal the recomputed engine and the golden snapshot. It says NOTHING about a model: replay fixtures are
hand-authored.
"""

from __future__ import annotations

import eval_runner as er
import pytest

SPECS = er.load_specs()
_RESULTS: dict[str, er.SpecResult] = {}


_TABLES = ("decisions", "decision_assessments", "evidence", "claims", "agent_runs", "audit_logs", "dq_checks", "syntheses",
           "decision_reviews", "decision_records", "decision_briefs", "customer_insights", "recommendations", "analysis_results")
_BASELINE: dict[str, int] = {}


def _counts(engine) -> dict[str, int]:
    from sqlalchemy import text
    with engine.connect() as c:
        return {t: c.execute(text(f"select count(*) from {t}")).scalar() for t in _TABLES}


@pytest.fixture(scope="module", autouse=True)
def _write_results_when_complete(engine):
    _BASELINE.update(_counts(engine))
    yield
    if len(_RESULTS) == len(SPECS):
        er.write_results([_RESULTS[s["id"]] for s in SPECS], SPECS)


# ---------------------------------------------------------------- the specs themselves
def test_there_are_at_least_fourteen_well_formed_synthetic_specs_with_the_required_groups():
    assert len(SPECS) >= 14
    for spec in SPECS:
        assert er.validate_spec(spec) == [], (spec.get("id"), er.validate_spec(spec))
    groups = [s["group"] for s in SPECS]
    assert groups.count("core") == 4 and groups.count("variant") == 6 and groups.count("extra") >= 4
    assert len({s["id"] for s in SPECS}) == len(SPECS)
    assert {s["id"] for s in SPECS if s["group"] == "core"} == {"core_ai_coach", "core_community", "core_onboarding", "core_pricing"}


def test_no_spec_chooses_a_band_in_advance():
    """D7-01: the only band value a spec may state is `golden`."""
    for spec in SPECS:
        assert spec["expect"].get("band") in (None, "golden")
        assert "ddi" not in spec["expect"] and "ddi_band" not in spec["expect"]


def test_the_golden_snapshot_has_the_required_header_and_covers_every_spec():
    golden = er.load_golden()
    assert golden, "run scripts/eval_snapshot.py --write"
    assert golden["header"].startswith("observed frozen-engine output, recorded ")
    assert "approved by PO at Day-7 verification" in golden["header"]
    assert golden["synthetic"] is True
    assert set(golden["specs"]) == {s["id"] for s in SPECS}


def test_the_snapshot_records_the_released_parameter_versions_and_hashes():
    from app.core.params import get_ddi_params, get_nbe_params
    ddi, nbe = get_ddi_params(), get_nbe_params()
    for sid, snap in er.load_golden()["specs"].items():
        if snap["state"] is None:
            continue
        assert (snap["ddi_params_version"], snap["ddi_params_hash"]) == (ddi.version, ddi.content_hash), sid
        assert (snap["nbe_params_version"], snap["nbe_params_hash"]) == (nbe.version, nbe.content_hash), sid


# ---------------------------------------------------------------- one test per spec
@pytest.mark.parametrize("spec", SPECS, ids=[s["id"] for s in SPECS])
def test_spec(spec, session, seed):
    res = er.run_spec(session, seed, spec)
    _RESULTS[spec["id"]] = res
    assert res.error is None, res.error
    detail = [f"{c.name}: expected {c.expected!r} observed {c.observed!r} {c.note}" for c in res.unexpected_failures]
    assert not res.unexpected_failures, f"{spec['id']}: " + " | ".join(detail)
    assert not res.stale_gaps, f"{spec['id']}: a documented known gap now passes; update the spec: {[c.name for c in res.stale_gaps]}"
    # every known gap is real: it appears as a failed check in the report
    assert len([c for c in res.checks if c.known_gap and not c.ok]) == len(spec.get("known_gaps", []))
    # the stored result equals the recomputed frozen engine whenever the stored facts are current
    names = {c.name for c in res.checks}
    if res.extras.get("recompute") and res.extras["recompute"]["fingerprint_matches"]:
        assert {"stored_equals_recomputed_engine", "ddi_reproducible"} <= names


def test_the_evaluation_did_not_change_the_database(engine):
    """Nothing the specs did is committed: the row counts of the product tables are what they were before the first spec ran."""
    assert _BASELINE, "the baseline is taken before the first test of this module"
    assert _counts(engine) == _BASELINE
