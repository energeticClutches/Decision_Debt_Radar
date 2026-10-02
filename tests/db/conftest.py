"""Database test fixtures. Tests skip cleanly when PostgreSQL (or the seed) is not available.

All data-changing tests run inside a transaction that is rolled back, so the seeded database
is never modified.
"""

import os
from pathlib import Path

import psycopg
import pytest

ROOT = Path(__file__).resolve().parents[2]


def database_url() -> str:
    url = os.environ.get("DATABASE_URL")
    if not url:
        env = ROOT / ".env"
        if env.exists():
            for line in env.read_text(encoding="utf-8").splitlines():
                if line.startswith("DATABASE_URL="):
                    url = line.split("=", 1)[1].strip()
    if not url:
        pytest.skip("DATABASE_URL not configured")
    return url.replace("postgresql+psycopg://", "postgresql://", 1)


@pytest.fixture(scope="session")
def dsn() -> str:
    url = database_url()
    try:
        with psycopg.connect(url, connect_timeout=5):
            pass
    except psycopg.OperationalError as exc:  # pragma: no cover
        pytest.skip(f"PostgreSQL not reachable: {exc}")
    return url


@pytest.fixture()
def conn(dsn):
    c = psycopg.connect(dsn)
    c.execute("SET TIME ZONE 'UTC'")
    c.execute("SELECT set_config('ddr.as_of', '2026-10-01', false)")
    try:
        yield c
    finally:
        c.rollback()
        c.close()


@pytest.fixture(scope="session")
def seeded(dsn):
    with psycopg.connect(dsn) as c:
        try:
            n = c.execute("SELECT count(*) FROM fc_.users").fetchone()[0]
        except psycopg.errors.UndefinedTable:
            pytest.skip("schema not migrated")
    if n == 0:
        pytest.skip("database not seeded (run python -m database.seed.run)")
    return n


class Ids:
    """Look up seeded deterministic ids."""

    def __init__(self, conn):
        q = lambda sql: conn.execute(sql).fetchone()[0]  # noqa: E731
        self.org = q("SELECT id FROM organizations LIMIT 1")
        self.team = q("SELECT id FROM teams WHERE name = 'Product'")
        self.pm = q("SELECT id FROM users WHERE role = 'pm' ORDER BY email LIMIT 1")
        self.executive = q("SELECT id FROM users WHERE role = 'executive'")
        self.metric = q("SELECT id FROM metrics WHERE name = 'd90_retention'")
        self.metric_no_ds = None
        self.es_events = q("SELECT id FROM evidence_sources WHERE ref = 'fc_.events'")
        self.es_subs = q("SELECT id FROM evidence_sources WHERE ref = 'fc_.subscriptions'")
        self.es_feedback = q("SELECT id FROM evidence_sources WHERE ref = 'fc_.feedback'")


@pytest.fixture()
def ids(conn, seeded):
    return Ids(conn)


def new_decision(conn, ids, **over):
    """Insert a valid decision (stage 'created'). Returns its id."""
    vals = dict(
        title="Test decision", description="d", hypothesis="If we do X then metric increases.",
        decision_due_date="2026-12-31", risk_level="medium", decision_type="product_feature_investment",
        criteria='["Evidence that would change our mind goes here"]', metric=ids.metric,
    )
    vals.update(over)
    return conn.execute(
        "INSERT INTO decisions (org_id, team_id, title, description, hypothesis, success_metric_id, decision_due_date,"
        " risk_level, change_my_mind_criteria, decision_type, canvas_completed_at, owner_id, is_synthetic)"
        " VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s::jsonb,%s,now(),%s,true) RETURNING id",
        (ids.org, ids.team, vals["title"], vals["description"], vals["hypothesis"], vals["metric"],
         vals["decision_due_date"], vals["risk_level"], vals["criteria"], vals["decision_type"], ids.pm),
    ).fetchone()[0]
