"""Data quality: T-DQ-1 (idempotent re-runs), T-DQ-2 (reconciliation table), T-DQ-4 and T-DQ-5 (seeded scenarios),
T-DQ-6 (facts builder reads checks by decision_id). T-DQ-3 (impact rule) is in test_day4_stats.py."""

from __future__ import annotations

import pytest
from day4_support import clone_decision, no_run, pipeline
from flow import Flow
from sqlalchemy import select, text

from app.analytics import dq as dq_mod
from app.analytics import dq_store
from app.analytics.dq import DqFinding
from app.core.params import get_analytics_params, get_tenant_config
from app.db import models as m
from app.repositories import dq as dq_repo
from app.repositories.evidence_facts import build_facts, evidence_fingerprint
from app.analytics.executor import ReadOnlyExecutor

PARAMS, TENANT = get_analytics_params(), get_tenant_config()


@pytest.fixture()
def flow(session, seed):
    return Flow(session, seed)


@pytest.fixture(scope="module")
def executor(engine):
    return ReadOnlyExecutor(engine)


@pytest.fixture(scope="module")
def runs(engine, executor):
    """Findings of the four seeded scenarios, computed once (read-only, nothing stored)."""
    from sqlalchemy.orm import Session
    out = {}
    with Session(engine) as s:
        for d in s.scalars(select(m.Decision).where(m.Decision.scenario_key.is_not(None))):
            metric = s.get(m.Metric, d.success_metric_id)
            linked = s.scalars(select(m.Experiment).where(m.Experiment.decision_id == d.id)).first() is not None
            plan = dq_mod.plan_for(TENANT, metric_name=metric.name, scenario_key=d.scenario_key, linked_experiments=linked)
            out[d.scenario_key] = dq_mod.run_checks(executor, PARAMS, TENANT, plan, __import__("datetime").date(2026, 10, 1))
    return out


def by_target(run, check_type=None):
    return {(f.check_type, f.target): f for f in run.findings if check_type in (None, f.check_type)}


# ---------------------------------------------------------------- T-DQ-4
def test_dq_4_onboarding_def_onb_002_is_critical_in_the_lineage_and_def_onb_001_is_warn(runs):
    f = by_target(runs["onboarding"])
    def_002 = f[("volume", "onboarding_completed@android")]
    assert def_002.severity == "critical" and def_002.in_lineage is True
    assert def_002.size == pytest.approx(0.6242, abs=1e-3) and def_002.size >= 0.5        # the 60% drop
    def_001 = f[("volume", "onboarding_step_2_completed@android")]
    assert def_001.raw_severity == "critical" and def_001.severity == "warn" and def_001.in_lineage is False
    assert def_001.size == pytest.approx(1.0)                                              # a 100% drop, capped at warn
    seq = f[("sequence", "onboarding_step_3_completed>onboarding_step_2_completed@android")]
    assert seq.raw_severity == "critical" and seq.severity == "warn" and seq.in_lineage is False
    assert seq.size == pytest.approx(0.2963, abs=1e-3)
    # nothing else is a finding: ios and web are clean, and so are completeness, duplicates and referential integrity
    findings = {k for k, v in f.items() if v.severity != "pass"}
    assert findings == {("volume", "onboarding_completed@android"), ("volume", "onboarding_step_2_completed@android"),
                        ("sequence", "onboarding_step_3_completed>onboarding_step_2_completed@android")}
    assert dq_mod.summarize(runs["onboarding"].findings) == {"pass": 41, "warn": 2, "critical": 1}
    # every check type ran
    assert {c for c, _ in f} == {"volume", "sequence", "completeness", "duplicates", "referential"}


def test_dq_4_the_stored_onboarding_rows_carry_target_value_threshold_and_the_lineage_flag(session, seed, flow):
    d = clone_decision(flow, seed, "onboarding")
    pipeline(session).stage_dq(d, no_run())
    rows = {c.target: c for c in dq_repo.list_for_decision(session, d.id) if c.severity != "pass"}
    assert set(rows) == {"onboarding_completed@android", "onboarding_step_2_completed@android",
                         "onboarding_step_3_completed>onboarding_step_2_completed@android"}
    crit = rows["onboarding_completed@android"]
    assert (crit.severity, crit.status, crit.check_type, crit.affects_success_metric) == ("critical", "open", "volume", True)
    assert crit.affects_metric_id == d.success_metric_id and crit.assessment_id is None and crit.decision_id == d.id
    assert crit.check_key == f"{crit.data_source_id}|volume|onboarding_completed@android"
    assert float(crit.observed_value) == pytest.approx(0.6242, abs=1e-3) and float(crit.threshold) == 0.5
    assert crit.last_run_at is not None and crit.source_snapshot and "fc_.v_events" in crit.source_snapshot
    assert "fell 62%" in crit.finding
    warn = rows["onboarding_step_2_completed@android"]
    assert (warn.severity, warn.affects_success_metric, warn.affects_metric_id) == ("warn", False, None)
    assert float(warn.observed_value) == pytest.approx(1.0) and "capped at warn" in warn.finding
    assert rows["onboarding_step_3_completed>onboarding_step_2_completed@android"].severity == "warn"


# ---------------------------------------------------------------- T-DQ-5
@pytest.mark.parametrize("scenario", ["ai_coach", "community", "pricing"])
def test_dq_5_the_other_scenarios_have_no_critical_finding(runs, scenario):
    run = runs[scenario]
    assert run.findings, "checks ran"
    assert not [f for f in run.findings if f.severity == "critical"]
    assert not [f for f in run.findings if f.raw_severity == "critical"]


def test_dq_5_the_other_scenarios_findings_in_detail(runs):
    for scenario in ("ai_coach", "community", "pricing"):
        assert dq_mod.summarize(runs[scenario].findings)["warn"] == 0, scenario       # fully clean on the seeded data
    # the lineage event of the AI Coach / Community decisions is app_open: steady across platforms
    f = by_target(runs["ai_coach"], "volume")
    for platform in ("android", "ios", "web"):
        assert f[("volume", f"app_open@{platform}")].severity == "pass" and f[("volume", f"app_open@{platform}")].in_lineage
    assert not f[("volume", "ai_coach_session@web")].in_lineage


# ---------------------------------------------------------------- T-DQ-1
@pytest.mark.parametrize("scenario", ["pricing", "community"])
def test_dq_1_rerunning_unchanged_data_gives_the_same_rows_count_and_ids(session, seed, flow, scenario):
    d = clone_decision(flow, seed, scenario)
    svc = pipeline(session)
    svc.stage_dq(d, no_run())
    first = {c.id: (c.check_key, c.severity, c.status, c.target) for c in dq_repo.list_for_decision(session, d.id)}
    assert first
    out2, status = svc.stage_dq(d, no_run())
    second = {c.id: (c.check_key, c.severity, c.status, c.target) for c in dq_repo.list_for_decision(session, d.id)}
    assert second == first                                                    # same ids, same keys, nothing added
    assert out2["reconcile"]["created"] == 0 and out2["reconcile"]["updated"] == 0 and status == "succeeded"
    assert len({c.check_key for c in dq_repo.list_for_decision(session, d.id)}) == len(first)         # no duplicates
    assert session.execute(text("SELECT count(*) FROM dq_checks WHERE decision_id=:d"), {"d": d.id}).scalar() == len(first)


# ---------------------------------------------------------------- T-DQ-2
def finding(target="volume-x@android", severity="warn", *, check_type="volume", ref="fc_.events", in_lineage=False, size=0.4):
    return DqFinding(check_type=check_type, data_source_ref=ref, target=target, view="fc_.v_events", in_lineage=in_lineage, size=size,
                     threshold=0.25, raw_severity=severity, severity=severity, finding=f"{target} is {severity}", snapshot="snap")


class Reconciler:
    """Runs dq_store.reconcile for one decision and exposes the stored row and the audit trail."""

    def __init__(self, session, seed, flow):
        self.session, self.seed = session, seed
        self.decision = flow.gathered()
        self.ds = {"fc_.events": seed.ds["FitConnect product events (fc_.events)"].id}
        self.now = flow.ctx.clock.now()

    def run(self, severity, **kw):
        summary = dq_store.reconcile(self.session, self.decision, [finding(severity=severity, **kw)], data_source_ids=self.ds, now=self.now)
        return summary, self.row()

    def row(self):
        (row,) = dq_repo.list_for_decision(self.session, self.decision.id)
        return row

    def set_status(self, status, by_user=True):
        row = self.row()
        row.status = status
        row.resolved_by = self.seed.analyst.id if by_user and status == "resolved" else None
        self.session.execute(text("UPDATE dq_checks SET status=:s, resolved_by=:r WHERE id=:i"),
                             {"s": status, "r": row.resolved_by if status == "resolved" else None, "i": row.id})
        self.session.refresh(row)

    def audits(self):
        return [(a.action, a.actor_type, a.actor_id, a.before, a.after) for a in self.session.scalars(
            select(m.AuditLog).where(m.AuditLog.entity_type == "dq_check").order_by(m.AuditLog.ts, m.AuditLog.id))]


@pytest.fixture()
def rec(session, seed, flow):
    return Reconciler(session, seed, flow)


def test_dq_2_new_check_is_created_open(rec):
    summary, row = rec.run("warn")
    assert summary.created == 1 and (row.status, row.severity) == ("open", "warn") and row.assessment_id is None
    assert rec.audits() == []                                              # creation is not an automatic status change


def test_dq_2_open_with_the_defect_present_stays_open_and_its_severity_is_updated(rec):
    rec.run("warn")
    summary, row = rec.run("critical")
    assert (row.status, row.severity) == ("open", "critical") and summary.severity_changed and not summary.reopened
    summary, row = rec.run("warn")
    assert (row.status, row.severity) == ("open", "warn")
    assert [a[0] for a in rec.audits()] == ["dq.severity_changed", "dq.severity_changed"]
    assert all(a[1] == "system" and a[2] is None for a in rec.audits())


def test_dq_2_open_with_the_defect_gone_stays_open_with_severity_pass_and_is_audited(rec):
    rec.run("critical")
    summary, row = rec.run("pass", size=0.0)
    assert (row.status, row.severity) == ("open", "pass") and summary.auto_cleared and not summary.status_changed
    (audit,) = rec.audits()
    assert audit[0] == "dq.auto_cleared_pending_review" and audit[1] == "system" and audit[2] is None
    assert audit[3] == {"status": "open", "severity": "critical"} and audit[4]["severity"] == "pass"
    # a pass row never blocks: it is open, but only a critical severity gates
    facts = build_facts(rec.session, rec.decision.id)
    assert [q.severity for q in facts.dq_issues] == ["pass"]
    # pass on an already-pass open row writes no audit row
    rec.run("pass", size=0.0)
    assert len(rec.audits()) == 1


def test_dq_2_accepted_stays_accepted_at_the_same_or_a_lower_severity(rec):
    rec.run("critical")
    rec.set_status("accepted")
    s1, row = rec.run("critical")
    assert row.status == "accepted" and not s1.reopened
    s2, row = rec.run("warn")
    assert (row.status, row.severity) == ("accepted", "warn") and not s2.reopened
    s3, row = rec.run("pass", size=0.0)
    assert (row.status, row.severity) == ("accepted", "pass")
    assert rec.audits() == []


def test_dq_2_accepted_at_a_worse_severity_is_reopened_with_an_audit_row(rec):
    rec.run("warn")
    rec.set_status("accepted")
    summary, row = rec.run("critical")
    assert (row.status, row.severity, row.resolved_by) == ("open", "critical", None) and summary.status_changed
    (audit,) = rec.audits()
    assert audit[0] == "dq.reopened" and audit[1] == "system" and audit[3]["status"] == "accepted" and audit[4]["status"] == "open"


def test_dq_2_resolved_with_the_defect_still_present_is_reopened_with_an_audit_row(rec):
    rec.run("critical")
    rec.set_status("resolved")
    assert rec.row().resolved_by is not None
    summary, row = rec.run("critical")
    assert (row.status, row.severity, row.resolved_by, row.resolved_at) == ("open", "critical", None, None) and summary.status_changed
    (audit,) = rec.audits()
    assert audit[0] == "dq.reopened" and audit[3] == {"status": "resolved", "severity": "critical"}
    # even a warn finding reopens a resolved check
    rec.set_status("resolved")
    summary, row = rec.run("warn")
    assert row.status == "open" and summary.reopened


def test_dq_2_resolved_with_the_defect_gone_stays_resolved(rec):
    rec.run("critical")
    rec.set_status("resolved")
    summary, row = rec.run("pass", size=0.0)
    assert (row.status, row.severity) == ("resolved", "pass") and not summary.status_changed
    assert row.resolved_by is not None and rec.audits() == []


def test_dq_2_a_status_change_after_an_assessment_marks_it_stale(session, seed, flow):
    """The DQ stage of the pipeline applies the Day-3 stale rule to an automatic reopen (here: on an assessed decision)."""
    d = clone_decision(flow, seed, "onboarding")
    svc = pipeline(session)
    svc.stage_dq(d, no_run())                                                  # creates the checks, DEF-ONB-002 is critical and open
    crit = next(c for c in dq_repo.list_for_decision(session, d.id) if c.target == "onboarding_completed@android")
    flow.add_evidence(d)
    flow.dq.set_status(seed.analyst, crit.id, "accepted")                      # accepted: the gate no longer blocks
    flow.assessments.run(seed.analyst, d.id)
    session.refresh(d)
    assert (d.lifecycle_stage, d.assessment_stale) == ("assessed", False)
    session.execute(text("UPDATE dq_checks SET status='resolved', resolved_by=:u WHERE id=:i"), {"u": seed.analyst.id, "i": crit.id})
    out, _ = svc.stage_dq(d, no_run())                                         # the defect is still there: reopened
    assert out["reconcile"]["reopened"] == [crit.check_key]
    session.refresh(d)
    assert (d.lifecycle_stage, d.assessment_stale) == ("evidence_gathered", True)
    actions = [(x.action, x.actor_type) for x in flow.audit.list_for_decision(seed.pm, d.id)]
    assert ("dq.reopened", "system") in actions and ("assessment.stale", "system") in actions


# ---------------------------------------------------------------- T-DQ-6
def test_dq_6_the_facts_builder_reads_checks_by_decision_id_and_a_null_assessment_id_gates(session, seed, flow):
    d = clone_decision(flow, seed, "onboarding")
    d2 = flow.gathered()
    pipeline(session).stage_dq(d, no_run())
    facts = build_facts(session, d.id)
    assert any(q.severity == "critical" and q.status == "open" for q in facts.dq_issues)
    assert all(session.get(m.DqCheck, q.id).assessment_id is None for q in facts.dq_issues)
    # the decision's own checks only
    assert build_facts(session, d2.id).dq_issues == ()
    # ... and a check with a NULL assessment_id gates the assessment (no assessment link needed)
    flow.add_evidence(d)
    result = flow.assessments.run(seed.analyst, d.id)
    assert result.state == "insufficient_evidence" and "open_critical_dq" in [r["code"] for r in result.blocking_reasons]
    reason = next(r for r in result.blocking_reasons if r["code"] == "open_critical_dq")
    assert len(reason["detail"]["dq_check_ids"]) == 1
    # accepting the check lifts the block and shows a warning (Day-3 semantics are unchanged)
    crit = next(q for q in dq_repo.list_for_decision(session, d.id) if q.severity == "critical")
    flow.dq.set_status(seed.analyst, crit.id, "accepted")
    d = session.get(m.Decision, d.id)
    assert d.lifecycle_stage == "evidence_gathered" and d.assessment_stale is True
    again = flow.assessments.run(seed.analyst, d.id)
    assert "open_critical_dq" not in [r["code"] for r in again.blocking_reasons]
    assert any(w["code"] == "accepted_critical_dq" for w in again.dimension_scores["warnings"]) or again.state == "insufficient_evidence"


def test_dq_6_the_fingerprint_covers_the_dq_checks_of_the_decision(session, seed, flow):
    d = clone_decision(flow, seed, "pricing")
    f0 = evidence_fingerprint(session, d.id)
    pipeline(session).stage_dq(d, no_run())
    f1 = evidence_fingerprint(session, d.id)
    assert f1 != f0
    row = dq_repo.list_for_decision(session, d.id)[0]
    session.execute(text("UPDATE dq_checks SET severity='warn' WHERE id=:i"), {"i": row.id})
    assert evidence_fingerprint(session, d.id) != f1
    # unrelated churn (last_run_at, snapshot) does not change it
    f2 = evidence_fingerprint(session, d.id)
    session.execute(text("UPDATE dq_checks SET last_run_at = now(), source_snapshot = 'changed' WHERE decision_id=:d"), {"d": d.id})
    assert evidence_fingerprint(session, d.id) == f2
