"""Lifecycle and service tests against the real database, rolled back (brief section 4, tests 19-20, 22-25)."""

from __future__ import annotations

import itertools
import uuid
from datetime import date

import pytest
from flow import Flow, canvas, evidence_payload
from sqlalchemy import text
from sqlalchemy.exc import DBAPIError

from app.db import models as m
from app.domain import lifecycle as rules
from app.domain.errors import Forbidden, InvalidInput, NotFound, StateConflict
from app.services import apply_transition, unit_of_work


@pytest.fixture()
def flow(session, seed):
    return Flow(session, seed)


def raw(session, sql, **params):
    return session.execute(text(sql), params)


def db_rejects(session, sql, **params) -> bool:
    try:
        with session.begin_nested():
            raw(session, sql, **params)
    except DBAPIError:
        return True
    return False


# ------------------------------------------------------------------ 19. every transition pair, service and DB
def advance_to(flow: Flow, session, decision, stage: str) -> None:
    """Put a fresh decision into `stage` using only legal SQL steps (setup, bypassing the services)."""
    order = list(rules.STAGES)
    did = decision.id
    for step in order[1: order.index(stage) + 1]:
        if step == "assessed":
            raw(session, "INSERT INTO decision_assessments (decision_id, version, state, ddi_score, ddi_band, params_version,"
                         " params_hash, evidence_fingerprint, as_of_date, is_synthetic) VALUES (:d,1,'scored',10,'low',"
                         "'ddi_params_v0.1','h','f','2026-10-01',true)", d=did)
            raw(session, "UPDATE decisions SET lifecycle_stage='assessed', canvas_locked_at='2026-10-01T09:00:00Z' WHERE id=:d", d=did)
        elif step == "decided":
            raw(session, "INSERT INTO decision_records (decision_id, decided_by, outcome, rationale, is_synthetic)"
                         " VALUES (:d,:u,'approve','fine',true)", d=did, u=uuid.UUID(flow.seed.executive.id))
            raw(session, "UPDATE decisions SET lifecycle_stage='decided' WHERE id=:d", d=did)
        else:
            raw(session, "UPDATE decisions SET lifecycle_stage=:s WHERE id=:d", s=step, d=did)
    session.refresh(decision)
    assert decision.lifecycle_stage == stage


def prepare_target(flow: Flow, session, decision, from_stage: str, to_stage: str) -> None:
    """Satisfy the database preconditions of a legal transition (a completed assessment, a final record)."""
    if (from_stage, to_stage) == ("evidence_gathered", "assessed"):
        raw(session, "INSERT INTO decision_assessments (decision_id, version, state, ddi_score, ddi_band, params_version,"
                     " params_hash, evidence_fingerprint, as_of_date, is_synthetic) VALUES (:d,1,'scored',10,'low',"
                     "'ddi_params_v0.1','h','f','2026-10-01',true)", d=decision.id)
    if (from_stage, to_stage) == ("validated", "decided"):
        raw(session, "INSERT INTO decision_records (decision_id, decided_by, outcome, rationale, is_synthetic)"
                     " VALUES (:d,:u,'approve','fine',true)", d=decision.id, u=uuid.UUID(flow.seed.executive.id))


PAIRS = [(a, b) for a, b in itertools.product(rules.STAGES, rules.STAGES) if a != b]


@pytest.mark.parametrize("from_stage,to_stage", PAIRS)
def test_19_every_stage_pair_is_handled_identically_by_service_and_database(flow, session, from_stage, to_stage):
    legal = (from_stage, to_stage) in rules.LEGAL_TRANSITIONS
    d = flow.new_decision()
    advance_to(flow, session, d, from_stage)
    if legal:
        prepare_target(flow, session, d, from_stage, to_stage)
        with unit_of_work(session):
            apply_transition(session, d, to_stage, clock=flow.ctx.clock, lock_canvas=True)
        session.refresh(d)
        assert d.lifecycle_stage == to_stage
        assert d.assessment_stale is (to_stage == "evidence_gathered" and from_stage != "created")
    else:
        with pytest.raises(StateConflict):
            apply_transition(session, d, to_stage, clock=flow.ctx.clock)
        session.refresh(d)
        assert d.lifecycle_stage == from_stage
        # the database rejects the same pair on its own (backstop)
        assert db_rejects(session, "UPDATE decisions SET lifecycle_stage=:s, assessment_stale=true, "
                                   "canvas_locked_at=COALESCE(canvas_locked_at, now()) WHERE id=:d", s=to_stage, d=d.id)


def test_19_legal_transition_set_matches_the_documented_table():
    assert len(rules.LEGAL_TRANSITIONS) == 8
    assert ("created", "decided") not in rules.LEGAL_TRANSITIONS and ("decided", "validated") not in rules.LEGAL_TRANSITIONS
    assert rules.label("validated") == "Assessment validated by review"


# ------------------------------------------------------------------ 20. stale handling
def drive(flow: Flow, stage: str):
    d, a = flow.scored()
    if stage in ("challenged", "validated"):
        flow.to_challenged(d, a)
    if stage == "validated":
        flow.reviews.validate(flow.seed.pm, d.id)
    assert flow.stage(d) == stage
    return d, a


@pytest.mark.parametrize("stage", ["assessed", "challenged", "validated"])
def test_20_adding_or_changing_evidence_after_assessment_marks_stale_and_returns_to_evidence_gathered(flow, stage):
    d, _ = drive(flow, stage)
    ev = flow.evidence.add(flow.seed.analyst, d.id, evidence_payload(flow.seed, "behavioral", summary="a later item"))
    assert flow.stage(d) == "evidence_gathered" and d.assessment_stale is True
    assert flow.audit_actions(d)[-2:] == ["evidence.added", "assessment.stale"]
    # re-assess, return to the same stage, then change an existing item
    flow.assessments.run(flow.seed.analyst, d.id)
    assert flow.stage(d) == "assessed" and d.assessment_stale is False
    flow.evidence.update(flow.seed.ba, d.id, ev.id, {"strength_grade": "A"})
    assert flow.stage(d) == "evidence_gathered" and d.assessment_stale is True
    assert flow.audit_actions(d)[-2:] == ["evidence.updated", "assessment.stale"]


@pytest.mark.parametrize("stage", ["assessed", "challenged", "validated"])
def test_20_editing_the_canvas_after_the_lock_marks_stale_and_is_audited(flow, stage):
    d, _ = drive(flow, stage)
    assert d.canvas_locked_at is not None
    flow.decisions.edit_canvas(flow.seed.pm, d.id, {"hypothesis": "If we do Y then retention will decrease less."})
    assert flow.stage(d) == "evidence_gathered" and d.assessment_stale is True
    assert flow.audit_actions(d)[-2:] == ["canvas.edited", "assessment.stale"]
    last = flow.audit.list_for_decision(flow.seed.pm, d.id)[-2]
    assert last.after["canvas_changed_after_assessment"] is True


def test_20_canvas_edit_before_the_first_assessment_does_not_touch_the_stage(flow):
    d = flow.gathered()
    flow.decisions.edit_canvas(flow.seed.pm, d.id, {"title": "Renamed before any assessment"})
    assert flow.stage(d) == "evidence_gathered" and d.assessment_stale is False and d.canvas_locked_at is None


def test_20_canvas_validation_rules(flow, seed):
    with pytest.raises(InvalidInput):
        flow.decisions.create(seed.pm, canvas(seed, decision_due_date=date(2026, 9, 30)))      # CV-4: before today
    with pytest.raises(InvalidInput):
        flow.decisions.create(seed.pm, canvas(seed, change_my_mind_criteria=["too short"]))    # CV-5
    with pytest.raises(InvalidInput):
        flow.decisions.create(seed.pm, canvas(seed, decision_type="not_a_type"))                # CV-6
    d, warnings = flow.decisions.create(seed.pm, canvas(seed, hypothesis="We should just do it"))
    assert [w["code"] for w in warnings] == ["CV-2"]                                           # warn, not block
    assert d.lifecycle_stage == "created" and d.canvas_locked_at is None


# ------------------------------------------------------------------ 22. versioning
def test_22_versions_current_is_highest_including_partial_previous_scored_is_separate(flow):
    d, a1 = flow.scored()
    assert a1.version == 1 and a1.state == "scored" and flow.stage(d) == "assessed"
    flow.evidence.add(flow.seed.analyst, d.id, evidence_payload(flow.seed, "behavioral", summary="v2 evidence"))
    a2 = flow.assessments.run(flow.seed.analyst, d.id)
    flow.evidence.add(flow.seed.analyst, d.id, evidence_payload(flow.seed, "customer", summary="v3 evidence"))
    a3 = flow.assessments.run(flow.seed.analyst, d.id)
    assert [a1.version, a2.version, a3.version] == [1, 2, 3]
    current, previous = flow.assessments.current_and_previous(flow.seed.pm, d.id)
    assert current.id == a3.id and previous is None
    assert [a.version for a in flow.assessments.list(flow.seed.pm, d.id)] == [3, 2, 1]
    # a partial assessment becomes current (no silent fallback) and does not advance the stage
    stage_before = flow.stage(d)
    flow.insert_partial_assessment(d, 4)
    current, previous = flow.assessments.current_and_previous(flow.seed.pm, d.id)
    assert current.version == 4 and current.state == "partial"
    assert previous.version == 3 and previous.state == "scored"          # exposed separately as historical
    assert flow.stage(d) == stage_before


def test_22_an_assessment_runs_only_from_evidence_gathered(flow):
    d = flow.new_decision()                                              # created
    with pytest.raises(StateConflict):
        flow.assessments.run(flow.seed.analyst, d.id)
    flow.decisions.confirm_evidence(flow.seed.pm, d.id)
    a = flow.assessments.run(flow.seed.analyst, d.id)                    # evidence_gathered: ok
    assert a.version == 1
    with pytest.raises(StateConflict):                                   # assessed: not again without stale evidence
        flow.assessments.run(flow.seed.analyst, d.id)
    assert flow.assessments.list(flow.seed.pm, d.id)[0].version == 1     # nothing was stored by the rejected run


def test_22_the_assessment_stores_versions_hashes_fingerprint_and_as_of(flow):
    d, a = flow.scored()
    assert a.params_version == "ddi_params_v0.1" and len(a.params_hash) == 64
    assert a.nbe_params_version == "nbe_params_v0.1" and len(a.nbe_params_hash) == 64
    assert len(a.evidence_fingerprint) == 64 and a.as_of_date == date(2026, 10, 1)
    assert a.dimension_scores["params_hash"] == a.params_hash
    assert a.sensitivity["band_stable"] in (True, False)
    # an insufficient assessment for the same decision type: recommendations store blockers, not DDI points
    d2, a2 = flow.insufficient()
    assert a2.state == "insufficient_evidence" and a2.ddi_score is None and a2.sensitivity == {}
    recs = flow.recs.list_for_assessment(flow.seed.pm, a2.id)
    assert recs and all(float(r.expected_reduction) == 0 and r.blockers_resolved >= 1 for r in recs)


# ------------------------------------------------------------------ 23. decision record
def test_23_record_requires_validated_and_acknowledgement_for_insufficient(flow):
    d, a = flow.insufficient()                                           # state insufficient_evidence
    with pytest.raises(StateConflict):                                   # assessed, not validated
        flow.records.record(flow.seed.executive, d.id, "approve", "go", True)
    flow.to_validated(d, a)
    with pytest.raises(InvalidInput):                                    # BR-11
        flow.records.record(flow.seed.executive, d.id, "approve", "go", False)
    with pytest.raises(InvalidInput):                                    # blank rationale
        flow.records.record(flow.seed.executive, d.id, "approve", "   ", True)
    rec = flow.records.record(flow.seed.executive, d.id, "approve_conditional", "Proceed with conditions.", True)
    assert rec.outcome == "approve_conditional" and flow.stage(d) == "decided"
    assert flow.audit_actions(d)[-1] == "decision.recorded"


def test_23_a_scored_low_or_moderate_band_decision_needs_no_acknowledgement(flow, seed):
    d = flow.gathered(decision_type="strategy_or_market_entry")
    common = dict(strength_grade="A", observed_end=date(2026, 9, 30), n_sample=500)
    flow.evidence.add(seed.analyst, d.id, evidence_payload(
        seed, "behavioral", evidence_type="market", evidence_source_id=str(seed.es["fc_.subscriptions"].id), **common))
    flow.evidence.add(seed.analyst, d.id, evidence_payload(seed, "customer", **common))
    flow.evidence.add(seed.analyst, d.id, evidence_payload(seed, "financial", **common))
    a = flow.assessments.run(seed.analyst, d.id)
    assert a.state == "scored" and a.ddi_band in ("low", "moderate")
    flow.to_validated(d, a)
    flow.records.record(seed.executive, d.id, "approve", "Evidence is adequate.", False)
    assert flow.stage(d) == "decided"


def test_23_defer_keeps_the_record_returns_to_evidence_gathered_and_never_decides(flow):
    d, a = flow.insufficient()
    flow.to_validated(d, a)
    rec = flow.records.record(flow.seed.executive, d.id, "defer", "Need more evidence first.", True)
    assert rec.outcome == "defer"
    assert flow.stage(d) == "evidence_gathered" and d.assessment_stale is True
    assert flow.audit_actions(d)[-1] == "decision.deferred"
    assert [r.outcome for r in flow.records.list(flow.seed.pm, d.id)] == ["defer"]           # kept as history
    # a new assessment version is required before deciding again; the single final record may then follow
    a2 = flow.assessments.run(flow.seed.analyst, d.id)
    assert a2.version == 2
    flow.to_validated(d, a2)
    flow.records.record(flow.seed.executive, d.id, "reject", "Still not enough.", True)
    assert [r.outcome for r in flow.records.list(flow.seed.pm, d.id)] == ["defer", "reject"]
    assert flow.stage(d) == "decided"


def test_23_one_final_record_and_decided_blocks_all_further_writes(flow, seed):
    d, a = flow.insufficient()
    check = flow.insert_dq_check(a, seed.metrics["d90_retention"].data_source_id, "warn")
    rec_id = flow.recs.list_for_assessment(seed.pm, a.id)[0].id
    flow.to_validated(d, a)
    flow.records.record(seed.executive, d.id, "approve", "Decided.", True)
    assert flow.stage(d) == "decided"
    writes = [
        lambda: flow.records.record(seed.executive, d.id, "reject", "again", True),
        lambda: flow.evidence.add(seed.analyst, d.id, evidence_payload(seed, "behavioral")),
        lambda: flow.decisions.edit_canvas(seed.pm, d.id, {"title": "changed after the decision"}),
        lambda: flow.assessments.run(seed.analyst, d.id),
        lambda: flow.reviews.record_human_review(seed.pm, a.id, "ready", None),
        lambda: flow.reviews.validate(seed.pm, d.id),
        lambda: flow.recs.set_status(seed.pm, rec_id, "accepted", "x"),
        lambda: flow.dq.set_status(seed.analyst, check, "resolved"),
    ]
    for write in writes:
        with pytest.raises(StateConflict):
            write()
    assert len(flow.records.list(seed.pm, d.id)) == 1
    # and the database refuses the same writes without any service in the way
    for sql in ("UPDATE decisions SET title='x' WHERE id=:d",
                "INSERT INTO evidence (decision_id, evidence_source_id, evidence_type, summary, stance, strength_grade,"
                " observed_start, observed_end, created_by, is_synthetic) VALUES (:d, (SELECT id FROM evidence_sources LIMIT 1),"
                "'behavioral','s','supports','B','2026-09-01','2026-09-02','user',true)",
                "INSERT INTO decision_assessments (decision_id, version, state, blocking_reasons, params_version, params_hash,"
                " evidence_fingerprint, as_of_date, is_synthetic) VALUES (:d,9,'insufficient_evidence','[1]','v','h','f','2026-10-01',true)"):
        assert db_rejects(flow.session, sql, d=d.id), sql
    audit_ok = flow.session.execute(text(
        "INSERT INTO audit_logs (org_id, actor_type, action, entity_type, entity_id, is_synthetic)"
        " VALUES (:o,'system','probe','decision',:d,true) RETURNING id"), {"o": d.org_id, "d": d.id}).scalar()
    assert audit_ok is not None                      # audit_logs stays insert-only and is still allowed


# ------------------------------------------------------------------ 24. audit
def test_24_every_transition_and_status_change_writes_exactly_one_audit_row_with_actor(flow, seed):
    d = flow.new_decision()
    flow.decisions.confirm_evidence(seed.ba, d.id)
    flow.add_evidence(d, "behavioral", "customer", "financial", actor=seed.analyst)
    a = flow.assessments.run(seed.pm, d.id)
    rec = flow.recs.list_for_assessment(seed.pm, a.id)[0]
    flow.recs.set_status(seed.analyst, rec.id, "accepted", "will do")
    check = flow.insert_dq_check(a, seed.metrics["d90_retention"].data_source_id, "warn")
    flow.reviews.record_human_review(seed.leader, a.id, "ready", None)
    flow.reviews.validate(seed.executive, d.id)
    flow.records.record(seed.executive, d.id, "approve", "Done.", a.ddi_band in ("high", "critical"))
    rows = flow.audit.list_for_decision(seed.pm, d.id)
    expected = [("decision.created", seed.pm), ("decision.evidence_gathered", seed.ba), ("evidence.added", seed.analyst),
                ("evidence.added", seed.analyst), ("evidence.added", seed.analyst), ("assessment.completed", seed.pm),
                ("recommendation.status_changed", seed.analyst), ("review.completed", seed.leader),
                ("assessment.validated", seed.executive), ("decision.recorded", seed.executive)]
    assert [(r.action, str(r.actor_id)) for r in rows if not r.action.startswith("seed")] == \
        [(a_, actor.id) for a_, actor in expected]
    assert len({r.id for r in rows}) == len(rows)
    assert all(r.actor_type == "user" and r.entity_id is not None for r in rows)
    assert check                                                           # DQ status audit is covered in the next test


def test_24_dq_status_change_is_audited_once_and_marks_the_assessment_stale(flow, seed):
    d, a = flow.insufficient()
    check = flow.insert_dq_check(a, seed.metrics["d90_retention"].data_source_id, "critical")
    flow.dq.set_status(seed.analyst, check, "resolved", "fixed upstream")
    assert flow.audit_actions(d)[-2:] == ["dq_check.status_changed", "assessment.stale"]
    assert flow.stage(d) == "evidence_gathered" and d.assessment_stale is True
    with pytest.raises(StateConflict):                                    # already resolved
        flow.dq.set_status(seed.analyst, check, "accepted")


def test_24_rejected_transitions_are_logged_as_transition_rejected(flow, seed):
    d = flow.new_decision()
    with pytest.raises(StateConflict):
        flow.assessments.run(seed.analyst, d.id)                           # created: not allowed
    with pytest.raises(Forbidden):
        flow.decisions.confirm_evidence(seed.leader, d.id)                 # role not allowed
    actions = flow.audit_actions(d)
    assert actions.count("transition.rejected") == 2
    last = flow.audit.list_for_decision(seed.pm, d.id)[-1]
    assert last.after["attempted"] == "confirm_evidence" and str(last.actor_id) == seed.leader.id


# ------------------------------------------------------------------ 25. override
def test_25_needs_rework_blocks_validation_unless_a_human_review_with_a_reason_exists(flow, seed):
    d, a = flow.scored()
    flow.reviews.record_human_review(seed.pm, a.id, "needs_rework", "The cohort definition is unclear.")
    assert flow.stage(d) == "challenged"
    with pytest.raises(StateConflict, match="needs_rework"):
        flow.reviews.validate(seed.pm, d.id)
    # a 'ready' without a reason does not override a needs_rework verdict
    with pytest.raises(InvalidInput):
        flow.reviews.record_human_review(seed.pm, a.id, "ready", "   ")
    with pytest.raises(StateConflict):
        flow.reviews.validate(seed.pm, d.id)
    flow.reviews.record_human_review(seed.leader, a.id, "ready", "Reviewed the cohort definition with the analyst: acceptable.")
    flow.reviews.validate(seed.leader, d.id)
    assert flow.stage(d) == "validated"
    assert flow.audit_actions(d)[-1] == "assessment.override"
    # a needs_rework verdict requires a reason too
    d2, a2 = flow.scored()
    with pytest.raises(InvalidInput):
        flow.reviews.record_human_review(seed.pm, a2.id, "needs_rework", None)


def test_25_a_clean_ready_review_validates_without_an_override(flow, seed):
    d, a = flow.scored()
    flow.reviews.record_human_review(seed.pm, a.id, "ready", None)
    flow.reviews.validate(seed.pm, d.id)
    assert flow.audit_actions(d)[-1] == "assessment.validated"
    with pytest.raises(StateConflict):
        flow.reviews.validate(seed.pm, d.id)                               # already validated


def test_review_rules(flow, seed):
    d, a = flow.scored()
    with pytest.raises(Forbidden):
        flow.reviews.record_human_review(seed.analyst, a.id, "ready", None)    # analysts do not review
    with pytest.raises(NotFound):
        flow.reviews.record_human_review(seed.pm, str(uuid.uuid4()), "ready", None)
    # only the current assessment can be reviewed
    flow.evidence.add(seed.analyst, d.id, evidence_payload(seed, "behavioral", summary="new"))
    a2 = flow.assessments.run(seed.analyst, d.id)
    with pytest.raises(StateConflict):
        flow.reviews.record_human_review(seed.pm, a.id, "ready", None)
    flow.reviews.record_human_review(seed.pm, a2.id, "ready", None)
    # department leaders validate only their own team's decisions
    growth = flow.gathered(title="Growth decision", team_id=seed.team_growth, owner_id=seed.actors["pm2"].id)
    ga = flow.assessments.run(seed.analyst, growth.id)
    flow.reviews.record_human_review(seed.pm, ga.id, "ready", None)
    with pytest.raises(Forbidden):
        flow.reviews.validate(seed.leader, growth.id)                       # lead1 is on the Product team
    flow.reviews.validate(seed.executive, growth.id)


def test_evidence_validation_and_org_scoping(flow, seed):
    d = flow.gathered()
    bad = evidence_payload(seed, "behavioral", observed_start=date(2026, 9, 10), observed_end=date(2026, 9, 1))
    with pytest.raises(InvalidInput):
        flow.evidence.add(seed.analyst, d.id, bad)
    with pytest.raises(InvalidInput):
        flow.evidence.add(seed.analyst, d.id, evidence_payload(seed, "behavioral", ci_low=1.0, ci_high=0.5))
    with pytest.raises(InvalidInput):
        flow.evidence.add(seed.analyst, d.id, evidence_payload(seed, "behavioral", evidence_source_id=str(uuid.uuid4())))
    with pytest.raises(Forbidden):
        flow.evidence.add(seed.leader, d.id, evidence_payload(seed, "behavioral"))
    assert isinstance(m.Decision.__tablename__, str)
