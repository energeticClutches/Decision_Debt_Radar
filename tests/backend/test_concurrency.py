"""Concurrency tests (brief test 21) on a throwaway database with real, committed transactions.

A scratch database is created, migrated to head and dropped afterwards, so nothing is left behind in the seeded
database (audit_logs is insert-only and could not be cleaned up there).
"""

from __future__ import annotations

import os
import subprocess
import sys
import threading
import time
import uuid
from datetime import date
from pathlib import Path

import psycopg
import pytest
from sqlalchemy import create_engine, text
from sqlalchemy.orm import Session

from app.core.clock import FixedClock
from app.core.params import get_ddi_params, get_nbe_params
from app.domain.errors import StateConflict
from app.domain.permissions import Actor
from app.services import (
    AssessmentService,
    DecisionService,
    EvidenceService,
    ServiceContext,
)
from flow import canvas

ROOT = Path(__file__).resolve().parents[2]


@pytest.fixture(scope="module")
def scratch_url(sa_url):
    admin_url = sa_url.replace("postgresql+psycopg://", "postgresql://", 1)
    name = f"ddr_conc_{uuid.uuid4().hex[:8]}"
    try:
        admin = psycopg.connect(admin_url, autocommit=True, connect_timeout=5)
    except psycopg.OperationalError as exc:
        pytest.skip(f"PostgreSQL not reachable: {exc}")
    admin.execute(f"CREATE DATABASE {name}")
    url = f"{sa_url.rsplit('/', 1)[0]}/{name}"
    env = {**os.environ, "DATABASE_URL": url, "PYTHONPATH": str(ROOT / "backend")}
    up = subprocess.run([sys.executable, "-m", "alembic", "-c", "alembic.ini", "upgrade", "head"], cwd=ROOT / "database",
                        env=env, capture_output=True, text=True, timeout=300)
    try:
        assert up.returncode == 0, up.stderr[-2000:]
        yield url
    finally:
        admin.execute(f"DROP DATABASE IF EXISTS {name} WITH (FORCE)")
        admin.close()


@pytest.fixture(scope="module")
def world(scratch_url):
    eng = create_engine(scratch_url, future=True)
    ids = {k: uuid.uuid4() for k in ("org", "team", "pm", "analyst", "ds", "metric", "es1", "es2", "es3")}
    with eng.begin() as c:
        c.execute(text("INSERT INTO organizations (id,name,industry,is_synthetic) VALUES (:o,'Scratch org','test',true)"), {"o": ids["org"]})
        c.execute(text("INSERT INTO teams (id,org_id,name,is_synthetic) VALUES (:t,:o,'T',true)"), {"t": ids["team"], "o": ids["org"]})
        for key, role in (("pm", "pm"), ("analyst", "product_analyst")):
            c.execute(text("INSERT INTO users (id,org_id,team_id,name,email,role,is_synthetic) VALUES (:i,:o,:t,:n,:e,:r,true)"),
                      {"i": ids[key], "o": ids["org"], "t": ids["team"], "n": key, "e": f"{key}@x.example", "r": role})
        c.execute(text("INSERT INTO data_sources (id,org_id,name,source_type,reliability_tier,tier_rationale,is_synthetic)"
                       " VALUES (:i,:o,'ds','csv',1,'t',true)"), {"i": ids["ds"], "o": ids["org"]})
        c.execute(text("INSERT INTO metrics (id,org_id,name,definition,unit,grain,data_source_id,is_synthetic)"
                       " VALUES (:i,:o,'m','def','ratio','day',:d,true)"), {"i": ids["metric"], "o": ids["org"], "d": ids["ds"]})
        for k, tier in (("es1", 1), ("es2", 2), ("es3", 3)):
            c.execute(text("INSERT INTO evidence_sources (id,org_id,data_source_id,title,source_type,reliability_tier,is_synthetic)"
                           " VALUES (:i,:o,:d,:t,'csv',:tier,true)"), {"i": ids[k], "o": ids["org"], "d": ids["ds"], "t": k, "tier": tier})
    actors = {k: Actor(str(ids[k]), str(ids["org"]), str(ids["team"]), role) for k, role in (("pm", "pm"), ("analyst", "product_analyst"))}
    yield eng, ids, actors
    eng.dispose()


def ctx(eng) -> ServiceContext:
    return ServiceContext(Session(eng, expire_on_commit=False), FixedClock(date(2026, 10, 1)), get_ddi_params(), get_nbe_params())


def new_gathered_decision(world):
    eng, ids, actors = world
    c = ctx(eng)
    d, _ = DecisionService(c).create(actors["pm"], canvas(
        type("S", (), {"metric_d90": str(ids["metric"])}), team_id=str(ids["team"]), owner_id=str(ids["pm"])))
    DecisionService(c).confirm_evidence(actors["pm"], d.id)
    ev = EvidenceService(c)
    for kind, es in (("behavioral", "es1"), ("customer", "es2"), ("financial", "es3")):
        ev.add(actors["analyst"], d.id, dict(
            evidence_source_id=str(ids[es]), evidence_type=kind, summary=kind, stance="supports", strength_grade="B",
            observed_start=date(2026, 8, 1), observed_end=date(2026, 9, 25), n_sample=500, effect_size=0.03,
            ci_low=0.02, ci_high=0.04, metric_id=str(ids["metric"]) if kind == "behavioral" else None,
            experiment_id=None, insight_id=None))
    did = d.id
    c.session.close()
    return did


def count(eng, sql, **p):
    with eng.connect() as c:
        return c.execute(text(sql), p).scalar()


def test_21_a_change_during_the_assessment_is_detected_409_and_nothing_is_stored(world):
    eng, ids, actors = world
    did = new_gathered_decision(world)
    # a stored statistic the facts depend on changes (and commits) after the facts were read: evidence_sources tier
    # is read through the evidence join, and is not protected by the decision row lock
    def concurrent_change():
        with eng.begin() as c:
            c.execute(text("UPDATE evidence_sources SET reliability_tier = 4 WHERE id = :i"), {"i": ids["es1"]})

    svc = AssessmentService(ctx(eng), checkpoint=concurrent_change)
    with pytest.raises(StateConflict) as exc:
        svc.run(actors["analyst"], did)
    assert exc.value.detail["reason"] == "evidence_changed"
    assert count(eng, "SELECT count(*) FROM decision_assessments WHERE decision_id=:d", d=did) == 0
    assert count(eng, "SELECT lifecycle_stage::text FROM decisions WHERE id=:d", d=did) == "evidence_gathered"
    # the rejected run left a transition.rejected audit row and nothing else
    assert count(eng, "SELECT count(*) FROM audit_logs WHERE action='transition.rejected' AND entity_id=:d", d=did) == 1
    # rerunning against the settled evidence succeeds
    a = AssessmentService(ctx(eng)).run(actors["analyst"], did)
    assert a.version == 1


def test_21_an_evidence_edit_waits_for_a_running_assessment_and_then_marks_it_stale(world):
    """Evidence writes lock the decision row, so they serialize behind a running assessment instead of racing it."""
    eng, ids, actors = world
    did = new_gathered_decision(world)
    inside = threading.Event()
    release = threading.Event()
    results: dict = {}

    def hook():
        inside.set()
        assert release.wait(10)

    def run_assessment():
        c = ctx(eng)
        try:
            results["assessment"] = AssessmentService(c, checkpoint=hook).run(actors["analyst"], did).version
        except Exception as exc:  # noqa: BLE001
            results["assessment_error"] = exc
        finally:
            c.session.close()

    def edit_evidence():
        c = ctx(eng)
        try:
            ev_id = c.session.execute(text("SELECT id FROM evidence WHERE decision_id=:d AND evidence_type='customer'"), {"d": did}).scalar()
            t0 = time.monotonic()
            EvidenceService(c).update(actors["analyst"], did, ev_id, {"strength_grade": "A"})
            results["edit_waited"] = time.monotonic() - t0
        except Exception as exc:  # noqa: BLE001
            results["edit_error"] = exc
        finally:
            c.session.close()

    t1 = threading.Thread(target=run_assessment)
    t1.start()
    assert inside.wait(10)
    t2 = threading.Thread(target=edit_evidence)
    t2.start()
    time.sleep(0.6)
    assert t2.is_alive() and "edit_waited" not in results           # blocked behind the assessment's row lock
    release.set()
    t1.join(15)
    t2.join(15)
    assert "assessment_error" not in results and "edit_error" not in results, results
    assert results["assessment"] == 1 and results["edit_waited"] >= 0.5
    assert count(eng, "SELECT lifecycle_stage::text FROM decisions WHERE id=:d", d=did) == "evidence_gathered"
    assert count(eng, "SELECT assessment_stale FROM decisions WHERE id=:d", d=did) is True
    assert count(eng, "SELECT count(*) FROM decision_assessments WHERE decision_id=:d", d=did) == 1


def test_21_two_concurrent_runs_give_one_assessment_and_a_clean_rejection_never_a_500(world):
    eng, ids, actors = world
    did = new_gathered_decision(world)
    barrier = threading.Barrier(2)
    outcomes: list = []

    def attempt():
        c = ctx(eng)
        try:
            barrier.wait(5)
            outcomes.append(("ok", AssessmentService(c).run(actors["analyst"], did).version))
        except StateConflict as exc:
            outcomes.append(("conflict", exc.message))
        except Exception as exc:  # noqa: BLE001
            outcomes.append(("error", repr(exc)))
        finally:
            c.session.close()

    threads = [threading.Thread(target=attempt) for _ in range(2)]
    for t in threads:
        t.start()
    for t in threads:
        t.join(20)
    kinds = sorted(k for k, _ in outcomes)
    assert kinds in (["conflict", "ok"], ["ok", "ok"]), outcomes          # never an unhandled error
    versions = count(eng, "SELECT array_agg(version ORDER BY version) FROM decision_assessments WHERE decision_id=:d", d=did)
    assert versions in ([1], [1, 2]) and versions == list(range(1, len(versions) + 1))
    assert count(eng, "SELECT count(*) FROM decision_assessments WHERE decision_id=:d", d=did) == len(versions)


def test_assessment_transaction_uses_the_explicitly_configured_isolation_level(world, scratch_url):
    """The assessment pins READ COMMITTED explicitly, even when the engine default is stronger, and verifies it."""
    from app.services.assessments import ASSESSMENT_ISOLATION_LEVEL
    assert ASSESSMENT_ISOLATION_LEVEL == "READ COMMITTED"
    eng, ids, actors = world
    seen = {}
    strict = create_engine(scratch_url, future=True, isolation_level="REPEATABLE READ")
    try:
        did = new_gathered_decision(world)
        c = ServiceContext(Session(strict, expire_on_commit=False), FixedClock(date(2026, 10, 1)), get_ddi_params(), get_nbe_params())
        assert c.session.execute(text("SHOW transaction_isolation")).scalar() == "repeatable read"
        c.session.rollback()                                    # no transaction yet: the service may pin its own level
        svc = AssessmentService(c, checkpoint=lambda: seen.update(level=c.session.execute(text("SHOW transaction_isolation")).scalar()))
        assert svc.run(actors["analyst"], did).version == 1
        assert seen["level"] == "read committed"
        c.session.close()
    finally:
        strict.dispose()


def test_assessment_is_rejected_when_the_isolation_level_cannot_be_pinned_and_is_wrong(world, scratch_url):
    """If a stronger-isolation transaction already began, the service refuses to run rather than trust the fingerprint."""
    eng, ids, actors = world
    strict = create_engine(scratch_url, future=True, isolation_level="REPEATABLE READ")
    try:
        did = new_gathered_decision(world)
        c = ServiceContext(Session(strict, expire_on_commit=False), FixedClock(date(2026, 10, 1)), get_ddi_params(), get_nbe_params())
        c.session.execute(text("SELECT 1"))                     # transaction begins at REPEATABLE READ
        with pytest.raises(StateConflict) as exc:
            AssessmentService(c).run(actors["analyst"], did)
        assert exc.value.detail["reason"] == "isolation_level"
        assert count(eng, "SELECT count(*) FROM decision_assessments WHERE decision_id=:d", d=did) == 0
        c.session.close()
    finally:
        strict.dispose()


def test_default_engine_is_pinned_to_read_committed():
    import inspect

    from app.db import session as db_session
    assert 'isolation_level="READ COMMITTED"' in inspect.getsource(db_session.get_engine)


def test_21_versions_run_one_after_the_other_are_1_2_3(world):
    eng, ids, actors = world
    did = new_gathered_decision(world)
    versions = []
    for round_ in range(3):
        c = ctx(eng)
        if round_:
            EvidenceService(c).add(actors["analyst"], did, dict(
                evidence_source_id=str(ids["es2"]), evidence_type="customer", summary=f"extra {round_}", stance="neutral",
                strength_grade="C", observed_start=date(2026, 9, 1), observed_end=date(2026, 9, 20), n_sample=None,
                effect_size=None, ci_low=None, ci_high=None, metric_id=None, experiment_id=None, insight_id=None))
        versions.append(AssessmentService(c).run(actors["analyst"], did).version)
        c.session.close()
    assert versions == [1, 2, 3]
