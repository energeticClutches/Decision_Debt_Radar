"""Fixtures for the Day-3 backend tests. DB tests skip cleanly when PostgreSQL or the seed is unavailable.

`session` runs inside an outer transaction that is rolled back; service commits become savepoint releases
(join_transaction_mode="create_savepoint"), so the seeded database is never modified.
"""

from __future__ import annotations

import os
import sys
from datetime import date
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent))

ROOT = Path(__file__).resolve().parents[2]
TODAY = date(2026, 10, 1)       # the seed's as-of date


def _database_url() -> str:
    url = os.environ.get("DATABASE_URL")
    if not url:
        env = ROOT / ".env"
        if env.exists():
            for line in env.read_text(encoding="utf-8").splitlines():
                if line.startswith("DATABASE_URL="):
                    url = line.split("=", 1)[1].strip()
    if not url:
        pytest.skip("DATABASE_URL not configured")
    return url


@pytest.fixture(scope="session")
def sa_url() -> str:
    url = _database_url()
    if url.startswith("postgresql://"):
        url = url.replace("postgresql://", "postgresql+psycopg://", 1)
    return url


@pytest.fixture(scope="session")
def engine(sa_url):
    from sqlalchemy import create_engine, text
    eng = create_engine(sa_url, future=True)
    try:
        with eng.connect() as c:
            n = c.execute(text("SELECT count(*) FROM fc_.users")).scalar()
            if n == 0:
                pytest.skip("database not seeded (run python -m database.seed.run)")
            c.execute(text("SELECT blockers_resolved FROM recommendations LIMIT 0"))
            c.execute(text("SELECT expected_direction FROM decisions LIMIT 0"))        # migration 0005
    except Exception as exc:  # noqa: BLE001
        pytest.skip(f"PostgreSQL not reachable, not migrated to 0005, or not seeded: {exc}")
    yield eng
    eng.dispose()


@pytest.fixture()
def session(engine):
    from sqlalchemy.orm import Session
    conn = engine.connect()
    outer = conn.begin()
    s = Session(bind=conn, join_transaction_mode="create_savepoint", expire_on_commit=False)
    try:
        yield s
    finally:
        s.close()
        outer.rollback()
        conn.close()


class Seed:
    """Seeded deterministic ids (database/seed/core_seed.py)."""

    def __init__(self, session):
        from sqlalchemy import select

        from app.db import models as m
        from app.domain.permissions import Actor
        self.session = session
        users = {u.email.split("@")[0]: u for u in session.scalars(select(m.User))}
        self.actors = {k: Actor(str(u.id), str(u.org_id), str(u.team_id) if u.team_id else None, u.role, u.name)
                       for k, u in users.items()}
        self.org = str(users["pm1"].org_id)
        teams = {t.name: str(t.id) for t in session.scalars(select(m.Team))}
        self.team_product, self.team_growth = teams["Product"], teams["Growth"]
        self.metrics = {mm.name: mm for mm in session.scalars(select(m.Metric))}
        self.metric_d90 = str(self.metrics["d90_retention"].id)
        self.metric_conv = str(self.metrics["paid_conversion_rate"].id)
        self.ds = {d.name: d for d in session.scalars(select(m.DataSource))}
        self.es = {e.ref: e for e in session.scalars(select(m.EvidenceSource))}
        self.decisions = {d.scenario_key: d for d in session.scalars(select(m.Decision)) if d.scenario_key}

    @property
    def pm(self):
        return self.actors["pm1"]

    @property
    def ba(self):
        return self.actors["ba1"]

    @property
    def analyst(self):
        return self.actors["pa1"]

    @property
    def leader(self):
        return self.actors["lead1"]

    @property
    def executive(self):
        return self.actors["exec1"]

    @property
    def bizops(self):
        return self.actors["biz1"]


@pytest.fixture()
def seed(session):
    return Seed(session)
