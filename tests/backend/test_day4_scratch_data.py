"""T-EVD-2 on a throwaway database with real, committed transactions: when the SOURCE DATA changes, a re-run keeps the same
number of evidence items, updates their values in place and leaves the decision stale. (The seeded FitConnect data is
never modified: a small synthetic fc_ dataset is created in a scratch database, which is dropped afterwards.)"""

from __future__ import annotations

import os
import subprocess
import sys
import uuid
from datetime import date
from pathlib import Path

import psycopg
import pytest
from day4_support import no_run
from flow import canvas
from sqlalchemy import create_engine, select, text
from sqlalchemy.orm import Session

from app.analytics.executor import ReadOnlyExecutor
from app.core.clock import FixedClock
from app.core.params import get_analytics_params, get_ddi_params, get_nbe_params, get_tenant_config
from app.db import models as m
from app.domain.permissions import Actor
from app.repositories import analysis as analysis_repo
from app.repositories import audit as audit_repo
from app.services import DecisionService, PipelineService, ServiceContext
from app.services.base import unit_of_work

ROOT = Path(__file__).resolve().parents[2]
AS_OF = date(2026, 10, 1)
EXP_KEY = "scratch_price_test"


@pytest.fixture(scope="module")
def scratch_url(sa_url):
    admin_url = sa_url.replace("postgresql+psycopg://", "postgresql://", 1)
    name = f"ddr_day4_{uuid.uuid4().hex[:8]}"
    try:
        admin = psycopg.connect(admin_url, autocommit=True, connect_timeout=5)
    except psycopg.OperationalError as exc:
        pytest.skip(f"PostgreSQL not reachable: {exc}")
    admin.execute(f"CREATE DATABASE {name}")
    url = f"{sa_url.rsplit('/', 1)[0]}/{name}"
    env = {**os.environ, "DATABASE_URL": url, "PYTHONPATH": str(ROOT / "backend")}
    up = subprocess.run([sys.executable, "-m", "alembic", "-c", "alembic.ini", "upgrade", "head"], cwd=ROOT / "database", env=env,
                        capture_output=True, text=True, timeout=300)
    try:
        assert up.returncode == 0, up.stderr[-2000:]
        yield url
    finally:
        admin.execute(f"DROP DATABASE IF EXISTS {name} WITH (FORCE)")
        admin.close()


@pytest.fixture(scope="module")
def world(scratch_url):
    eng = create_engine(scratch_url, future=True)
    ids = {k: uuid.uuid4() for k in ("org", "team", "pm", "analyst", "ds_events", "ds_subs", "ds_exp", "metric")}
    with eng.begin() as c:
        c.execute(text("INSERT INTO organizations (id,name,industry,is_synthetic) VALUES (:o,'Scratch org','test',true)"), {"o": ids["org"]})
        c.execute(text("INSERT INTO teams (id,org_id,name,is_synthetic) VALUES (:t,:o,'T',true)"), {"t": ids["team"], "o": ids["org"]})
        for key, role in (("pm", "pm"), ("analyst", "product_analyst")):
            c.execute(text("INSERT INTO users (id,org_id,team_id,name,email,role,is_synthetic) VALUES (:i,:o,:t,:n,:e,:r,true)"),
                      {"i": ids[key], "o": ids["org"], "t": ids["team"], "n": key, "e": f"{key}@x.example", "r": role})
        for key, name, tier, ref in (("ds_events", "events", 2, "fc_.events"), ("ds_subs", "subscriptions", 1, "fc_.subscriptions"),
                                     ("ds_exp", "experiments", 2, "fc_.experiment_assignments")):
            c.execute(text("INSERT INTO data_sources (id,org_id,name,source_type,reliability_tier,tier_rationale,is_synthetic)"
                           " VALUES (:i,:o,:n,'csv',:t,'t',true)"), {"i": ids[key], "o": ids["org"], "n": name, "t": tier})
            c.execute(text("INSERT INTO evidence_sources (org_id,data_source_id,title,ref,source_type,reliability_tier,is_synthetic)"
                           " VALUES (:o,:d,:n,:r,'csv',:t,true)"), {"o": ids["org"], "d": ids[key], "n": name, "r": ref, "t": tier})
        c.execute(text("INSERT INTO metrics (id,org_id,name,definition,unit,grain,data_source_id,is_synthetic)"
                       " VALUES (:i,:o,'paid_conversion_rate','def','ratio','week',:d,true)"), {"i": ids["metric"], "o": ids["org"], "d": ids["ds_subs"]})
        # a small synthetic fc_ dataset: 3000 Canadian trial starters, signups Jan to Aug 2026, a third convert
        c.execute(text(
            "INSERT INTO fc_.users (user_id, signup_ts, platform, country, acquisition_channel, engagement_style, prior_engagement_tier)"
            " SELECT i, timestamptz '2026-01-01 00:00:00+00' + (i % 240) * interval '1 day' + i * interval '1 second', 'ios', 'CA',"
            " 'organic', 'solo_athlete', 'medium' FROM generate_series(1, 3000) AS i"))
        c.execute(text(
            "INSERT INTO fc_.subscriptions (subscription_id, user_id, plan, price_monthly, start_date, end_date, status)"
            " SELECT u.user_id, u.user_id, 'free_trial', 0, (u.signup_ts AT TIME ZONE 'UTC')::date,"
            " (u.signup_ts AT TIME ZONE 'UTC')::date + 14, CASE WHEN u.user_id % 3 = 0 THEN 'trial_converted' ELSE 'trial_expired' END"
            " FROM fc_.users u"))
        c.execute(text(
            "INSERT INTO fc_.experiment_assignments (experiment_key, user_id, variant, assigned_at)"
            " SELECT :k, i, CASE WHEN i % 2 = 0 THEN 'treatment_11_99' ELSE 'control_9_99' END, timestamptz '2026-05-01 00:00:00+00'"
            " FROM generate_series(1, 400) AS i"), {"k": EXP_KEY})
        c.execute(text(
            "INSERT INTO fc_.experiment_outcomes (experiment_key, user_id, metric_name, value)"
            " SELECT :k, i, 'converted_to_paid', (i % 3 = 0)::int FROM generate_series(1, 400) AS i"), {"k": EXP_KEY})
    actors = {k: Actor(str(ids[k]), str(ids["org"]), str(ids["team"]), role) for k, role in (("pm", "pm"), ("analyst", "product_analyst"))}
    yield eng, ids, actors
    eng.dispose()


def make_service(eng, session):
    ctx = ServiceContext(session, FixedClock(AS_OF), get_ddi_params(), get_nbe_params(), get_analytics_params(), get_tenant_config(),
                         ReadOnlyExecutor(eng))
    return PipelineService(ctx), ctx


def new_decision(world, eng):
    _, ids, actors = world
    with Session(eng, expire_on_commit=False) as s:
        svc, ctx = make_service(eng, s)
        fields = canvas(type("S", (), {"metric_d90": str(ids["metric"])}), team_id=str(ids["team"]), owner_id=str(ids["pm"]),
                        decision_type="pricing_change", expected_direction="no_material_decrease")
        d, _ = DecisionService(ctx).create(actors["pm"], fields)
        s.execute(text("UPDATE decisions SET scenario_key = 'pricing' WHERE id = :d"), {"d": d.id})
        s.execute(text(
            "INSERT INTO experiments (org_id, decision_id, name, hypothesis, design, start_date, end_date, status, primary_metric_id,"
            " planned_sample, mde, source_ref, planned_treatment_share, control_variant, outcome_key, is_synthetic)"
            " VALUES (:o,:d,'Scratch price test','h','rct','2026-05-01','2026-05-28','completed',:m,800,0.02,:k,0.5,'control_9_99',"
            "'converted_to_paid',true)"), {"o": ids["org"], "d": d.id, "m": ids["metric"], "k": EXP_KEY})
        s.commit()
        DecisionService(ctx).confirm_evidence(actors["pm"], d.id)
        return d.id


def rerun_analytics(eng, did, actors):
    """Stages 2, 4 and 5 for a decision at any stage, in one committed transaction (the pipeline entry point needs evidence_gathered)."""
    with Session(eng, expire_on_commit=False) as s:
        svc, ctx = make_service(eng, s)
        with unit_of_work(s):
            d = s.get(m.Decision, did, populate_existing=True)
            ids: list = []
            svc.stage_dq(d, no_run())
            svc.stage_quant(d, no_run(), ids)
            svc.stage_experiment(d, no_run(), ids)
            summary = svc.materializer.apply(d, ids)
        return summary


def state(eng, did):
    with Session(eng) as s:
        d = s.get(m.Decision, did)
        ev = list(s.scalars(select(m.Evidence).where(m.Evidence.decision_id == did).order_by(m.Evidence.evidence_type, m.Evidence.id)))
        return {"stage": d.lifecycle_stage, "stale": d.assessment_stale,
                "evidence": [(e.id, e.status, e.evidence_type, e.stance, e.strength_grade, float(e.effect_size) if e.effect_size is not None else None,
                              e.analysis_id, e.source_fingerprint, e.summary) for e in ev],
                "analyses": len(analysis_repo.list_for_decision(s, did)),
                "actions": [a.action for a in audit_repo.list_for_decision(s, did)]}


def test_evd_2_changing_the_source_data_keeps_n_updates_values_in_place_and_marks_the_decision_stale(world):
    eng, ids, actors = world
    did = new_decision(world, eng)
    with Session(eng, expire_on_commit=False) as s:
        svc, _ = make_service(eng, s)
        first = svc.run(actors["analyst"], did)
    assert first.partial is False and first.assessment.state in ("scored", "insufficient_evidence")
    before = state(eng, did)
    assert before["stage"] == "assessed" and before["stale"] is False and len(before["evidence"]) == 3
    assert {e[1] for e in before["evidence"]} == {"active"}

    # a re-run on unchanged data: still N, nothing stale
    same = rerun_analytics(eng, did, actors)
    assert (same.created, same.updated, same.unchanged) == (0, 0, 3)
    assert state(eng, did)["stage"] == "assessed" and state(eng, did)["stale"] is False

    # change the source data (committed): the treatment arm converts a lot more, and the post-April cohort converts
    with eng.begin() as c:
        c.execute(text("UPDATE fc_.experiment_outcomes SET value = 1 WHERE experiment_key = :k AND user_id % 2 = 0"), {"k": EXP_KEY})
        c.execute(text("UPDATE fc_.subscriptions SET status = 'trial_converted' WHERE start_date >= DATE '2026-04-01'"))
    changed = rerun_analytics(eng, did, actors)
    assert changed.updated == 3 and changed.created == 0 and changed.superseded == 0 and changed.stale is True
    after = state(eng, did)
    assert len(after["evidence"]) == 3 and {e[0] for e in after["evidence"]} == {e[0] for e in before["evidence"]}       # still N, same items
    assert {e[1] for e in after["evidence"]} == {"active"}
    old, new = {e[0]: e for e in before["evidence"]}, {e[0]: e for e in after["evidence"]}
    for eid in old:
        assert new[eid][7] != old[eid][7]                         # the source fingerprint changed
        assert new[eid][6] != old[eid][6]                         # it now points at the new analysis row (the old row is kept)
        assert new[eid][8] != old[eid][8]                         # the summary carries the new numbers
    experiment_id = next(e[0] for e in before["evidence"] if e[2] == "experiment")
    assert new[experiment_id][5] > old[experiment_id][5] + 0.2    # effect updated in place (treatment arm now converts)
    assert after["analyses"] == before["analyses"] + 4            # history is insert-only: comparison, segmentation, trend, experiment
    assert (after["stage"], after["stale"]) == ("evidence_gathered", True)                                         # the decision is stale
    assert "assessment.stale" in after["actions"] and "evidence.updated" in after["actions"]

    # the stale decision can run again: version 2 reflects the new values, version 1 is kept
    with Session(eng, expire_on_commit=False) as s:
        svc, _ = make_service(eng, s)
        second = svc.run(actors["analyst"], did)
    assert second.assessment.version == 2 and second.partial is False
    with Session(eng) as s:
        versions = [a.version for a in s.scalars(select(m.DecisionAssessment).where(m.DecisionAssessment.decision_id == did).order_by(m.DecisionAssessment.version))]
        assert versions == [1, 2]
    final = state(eng, did)
    assert len(final["evidence"]) == 3 and final["analyses"] == after["analyses"]          # nothing new in the analytics on the second run
