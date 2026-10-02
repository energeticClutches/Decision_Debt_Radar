"""NBE v0.2 (Day 4.1, Remediation 1): the success-metric blocker dependency under an open critical DQ issue.

Pure engine tests, no database. v0.1 is the original methodology and must behave exactly as at the Day-3 baseline f6209e9."""

from __future__ import annotations

import json
from dataclasses import replace

import pytest
from ddi_factories import AS_OF, METRIC, METRIC_DS, PARAMS, facts, item
from nbe_v01_cases import GOLDEN, build_outputs

from app.core.params import CONFIG_DIR, load_nbe_params, sha256_file
from app.domain.facts import DqIssue
from app.domain.nbe import recommend
from app.domain.nbe.params import BlockerDependency
from app.domain.ddi import assess

V01 = load_nbe_params("nbe_params_v0.1", ddi_params=PARAMS)
V02 = load_nbe_params("nbe_params_v0.2", ddi_params=PARAMS)
EVIDENCE_GATHERING = ("powered_holdout_test", "segment_level_analysis", "customer_interview_sprint", "targeted_survey",
                      "extend_observation_or_refresh_data", "financial_model_with_sensitivity")
CRITICAL_DQ = [DqIssue("q1", METRIC_DS, "critical", "open", affects_metric_id=METRIC)]


def onboarding_like(dtype="process_or_ux_change", dq=None, items=(), metric_ds=METRIC_DS):
    """No evidence at all, an open critical DQ issue on the success metric: min_items, min_types, success_metric_evidence,
    open_critical_dq all block (the seeded Onboarding state before DEF-ONB-002 is accepted)."""
    return facts(list(items), decision_type=dtype, dq=CRITICAL_DQ if dq is None else dq, metric_ds=metric_ds)


def run(f, nbe):
    r = assess(f, PARAMS, AS_OF)
    assert r.state == "insufficient_evidence"
    return r, recommend(r, f, PARAMS, nbe)


def claimed(rec) -> list[str]:
    """The blockers an insufficient-state recommendation claims (read from its explanation)."""
    if "Addresses" not in rec.why_this:
        return ["open_critical_dq"] if rec.action_id == "fix_dq_or_instrumentation" else []
    return sorted(b.strip() for b in rec.why_this.split(":", 1)[1].rstrip(".").split(","))


def by_id(recs):
    return {r.action_id: r for r in recs}


# ---------------------------------------------------------------- 7. version, hash, registration
def test_v02_hash_is_deterministic_registered_and_references_the_active_ddi_version():
    registry = json.loads((CONFIG_DIR / "params_hashes.json").read_text(encoding="utf-8"))
    path = CONFIG_DIR / "nbe" / "nbe_params_v0.2.yaml"
    assert V02.version == "nbe_params_v0.2" and V02.ddi_params_version == PARAMS.version == "ddi_params_v0.1"
    assert V02.content_hash == sha256_file(path) == registry["nbe_params_v0.2"]["sha256"]
    assert load_nbe_params("nbe_params_v0.2", ddi_params=PARAMS).content_hash == V02.content_hash       # stable across loads
    assert not path.read_bytes().startswith(b"\xef\xbb\xbf") and b"\r" not in path.read_bytes()
    assert V02.content_hash != V01.content_hash
    assert V02.blocker_dependencies == tuple(BlockerDependency(b, "open_critical_dq")
                                             for b in ("success_metric_evidence", "min_items", "min_types"))
    assert V01.blocker_dependencies == ()


def test_v01_is_preserved_byte_for_byte():
    assert V01.content_hash == "8a7c730edb77fc7b7f69cce487bce99fba5ace660f1c028c8cb6692221546ff7"
    assert V01.version == "nbe_params_v0.1"


# ---------------------------------------------------------------- 6. v0.1 behaviour unchanged
def test_v01_output_equals_the_day3_baseline_golden_for_every_fixture():
    golden = json.loads(GOLDEN.read_text(encoding="utf-8"))
    current = build_outputs(PARAMS, V01)
    assert set(current) == set(golden) and len(golden) > 250
    assert sum(1 for v in golden.values() if v) > 150                                      # the fixtures are not vacuous
    assert any(k.startswith("insufficient-") and v for k, v in golden.items())
    mismatched = [k for k in golden if current[k] != golden[k]]
    assert mismatched == []


def test_v01_still_lets_extending_observation_claim_success_metric_evidence_under_an_open_critical_dq_issue():
    _, recs = run(onboarding_like(), V01)
    r = by_id(recs)
    assert claimed(r["extend_observation_or_refresh_data"]) == ["min_items", "min_types", "success_metric_evidence"]
    assert r["extend_observation_or_refresh_data"].blockers_resolved == 3 and recs[0].action_id == "extend_observation_or_refresh_data"
    assert "segment_level_analysis" in r


# ---------------------------------------------------------------- 1, 2, 3. the dependency under an open critical DQ issue
def test_v02_evidence_gathering_actions_cannot_claim_any_blocker_while_the_dq_blocker_is_open():
    res, recs = run(onboarding_like(), V02)
    assert [x.code for x in res.blocking_reasons] == ["min_items", "min_types", "success_metric_evidence", "open_critical_dq"]
    r = by_id(recs)
    for action in EVIDENCE_GATHERING:                       # none can claim success_metric_evidence, min_items or min_types
        assert action not in r, action                      # nothing left to claim, so they are not listed (blockers_resolved >= 1 only)


def test_v02_fix_dq_is_the_only_and_first_recommendation_for_the_onboarding_state_without_a_hard_coded_order():
    _, recs = run(onboarding_like(), V02)
    assert [x.action_id for x in recs] == ["fix_dq_or_instrumentation"]
    fix = recs[0]
    assert fix.rank == 1 and fix.blockers_resolved == 1 and fix.group == "unblock_scoring" and fix.data_source_id == METRIC_DS
    assert "open_critical_dq" in fix.why_this and fix.relevance == 1.0
    assert fix.priority == pytest.approx(1.0 * 1 / 3.0)
    # the order comes from the dependency model: with the dependency list emptied (v0.1 rules) the others return and outrank it
    _, old = run(onboarding_like(), replace(V02, blocker_dependencies=()))
    assert old[0].action_id != "fix_dq_or_instrumentation" and len(old) > 1
    # a partial dependency list (only success_metric_evidence) leaves extend ranked first, so the widened list is what matters
    partial = replace(V02, blocker_dependencies=(BlockerDependency("success_metric_evidence", "open_critical_dq"),))
    assert run(onboarding_like(), partial)[1][0].action_id == "extend_observation_or_refresh_data"
    for rec in recs:
        assert rec.priority == pytest.approx(rec.relevance * rec.blockers_resolved / rec.effort_days)


def test_v02_the_onboarding_ranking_before_and_after_the_dependency():
    _, old = run(onboarding_like(), V01)
    _, new = run(onboarding_like(), V02)
    ext = by_id(old)["extend_observation_or_refresh_data"]
    assert (ext.blockers_resolved, ext.priority) == (3, pytest.approx(3.0)) and old[0].action_id == ext.action_id
    assert {x.action_id: x.rank for x in old}["fix_dq_or_instrumentation"] == 7
    assert [(x.action_id, x.rank) for x in new] == [("fix_dq_or_instrumentation", 1)]


# ---------------------------------------------------------------- 4. the dependency lifts once the DQ blocker is gone
@pytest.mark.parametrize("status", ["resolved", "accepted"])
def test_v02_once_the_dq_dependency_is_removed_blocked_actions_claim_success_metric_evidence_again(status):
    dq = [DqIssue("q1", METRIC_DS, "critical", status, affects_metric_id=METRIC)]
    res, recs = run(onboarding_like(dq=dq), V02)
    assert [x.code for x in res.blocking_reasons] == ["min_items", "min_types", "success_metric_evidence"]
    r = by_id(recs)
    assert claimed(r["extend_observation_or_refresh_data"]) == ["min_items", "min_types", "success_metric_evidence"]
    assert "success_metric_evidence" in claimed(r["powered_holdout_test"]) and "segment_level_analysis" in r
    assert "fix_dq_or_instrumentation" not in r
    # and it equals what v0.1 does in the same state: the dependency changes nothing without the DQ blocker
    _, v01 = run(onboarding_like(dq=dq), V01)
    assert [(x.action_id, x.blockers_resolved, x.priority) for x in recs] == [(x.action_id, x.blockers_resolved, x.priority) for x in v01]


# ---------------------------------------------------------------- 5. generic, not Onboarding-specific
@pytest.mark.parametrize("dtype", ["product_feature_investment", "pricing_change", "process_or_ux_change"])
def test_v02_the_rule_holds_for_other_decision_types_data_sources_and_evidence_sets(dtype):
    items = [item("a", type="customer", ds="ds-other"), item("b", type="financial")]          # evidence exists but none on the metric
    dq = [DqIssue("q9", "ds-metric-2", "critical", "open")]
    f = facts(items, decision_type=dtype, dq=dq, metric_ds="ds-metric-2")
    res, recs = run(f, V02)
    assert "open_critical_dq" in [x.code for x in res.blocking_reasons] and "success_metric_evidence" in [x.code for x in res.blocking_reasons]
    assert all("success_metric_evidence" not in claimed(x) for x in recs if x.action_id != "fix_dq_or_instrumentation")
    assert by_id(recs)["fix_dq_or_instrumentation"].data_source_id == "ds-metric-2"
    # v0.1 on the same facts lets evidence-gathering actions claim it
    _, old = run(f, V01)
    assert any("success_metric_evidence" in claimed(x) for x in old)


def test_v02_without_an_open_critical_dq_issue_nothing_changes():
    f = facts([item(f"b{i}", type="behavioral", metric_id=METRIC) for i in range(3)])         # min_types only, no DQ
    _, a = run(f, V01)
    _, b = run(f, V02)
    assert [(x.action_id, x.priority, x.blockers_resolved) for x in a] == [(x.action_id, x.priority, x.blockers_resolved) for x in b]
    # a warn-level or non-metric DQ issue does not trigger the dependency either
    f2 = onboarding_like(dq=[DqIssue("q1", "ds-elsewhere", "critical", "open")], metric_ds=METRIC_DS)
    _, c = run(f2, V02)
    _, d = run(f2, V01)
    assert [(x.action_id, x.priority) for x in c] == [(x.action_id, x.priority) for x in d]


def test_v02_the_rule_is_driven_by_configuration_not_by_action_or_blocker_names_in_code():
    # a different dependency in the configuration: min_items cannot be claimed while success_metric_evidence blocks,
    # except by an action that resolves success_metric_evidence itself
    custom = replace(V02, blocker_dependencies=(BlockerDependency("min_items", "success_metric_evidence"),))
    f = facts([])
    res, recs = run(f, custom)
    assert [x.code for x in res.blocking_reasons] == ["min_items", "min_types", "success_metric_evidence"]
    r = by_id(recs)
    assert set(claimed(r["powered_holdout_test"])) == {"min_items", "min_types", "success_metric_evidence"}      # it resolves the dependency
    assert "min_items" not in claimed(r["customer_interview_sprint"]) and claimed(r["customer_interview_sprint"]) == ["min_types"]
    assert claimed(r["financial_model_with_sensitivity"]) == ["min_types"]
    # an empty dependency list is exactly v0.1
    assert [(x.action_id, x.priority) for x in recommend(res, f, PARAMS, replace(V02, blocker_dependencies=()))] == \
        [(x.action_id, x.priority) for x in recommend(res, f, PARAMS, V01)]
