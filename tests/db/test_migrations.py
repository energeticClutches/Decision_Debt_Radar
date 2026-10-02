"""Alembic migration from an empty PostgreSQL database (and back), on a throwaway database."""

import os
import subprocess
import sys
import uuid
from pathlib import Path

import psycopg
import pytest

ROOT = Path(__file__).resolve().parents[2]


def alembic(env, *args):
    return subprocess.run([sys.executable, "-m", "alembic", "-c", "alembic.ini", *args], cwd=ROOT / "database",
                          env=env, capture_output=True, text=True, timeout=300)


@pytest.fixture()
def scratch_db(dsn):
    name = f"ddr_migtest_{uuid.uuid4().hex[:8]}"
    admin = psycopg.connect(dsn, autocommit=True)
    admin.execute(f"CREATE DATABASE {name}")
    base = dsn.rsplit("/", 1)[0]
    url = f"{base}/{name}"
    try:
        yield url
    finally:
        admin.execute(f"DROP DATABASE IF EXISTS {name} WITH (FORCE)")
        admin.close()


def test_upgrade_from_empty_database_then_downgrade_to_base(scratch_db):
    env = {**os.environ, "DATABASE_URL": scratch_db.replace("postgresql://", "postgresql+psycopg://", 1),
           "PYTHONPATH": str(ROOT / "backend")}
    up = alembic(env, "upgrade", "head")
    assert up.returncode == 0, up.stderr[-2000:]
    with psycopg.connect(scratch_db) as c:
        assert c.execute("SELECT version_num FROM alembic_version").fetchone()[0] == "0004"
        assert c.execute("SELECT count(*) FROM information_schema.tables WHERE table_schema='public' AND table_type='BASE TABLE' "
                         "AND table_name <> 'alembic_version'").fetchone()[0] == 22
        assert c.execute("SELECT count(*) FROM information_schema.tables WHERE table_schema='fc_' AND table_type='BASE TABLE'").fetchone()[0] == 9
        assert c.execute("SELECT count(*) FROM information_schema.views WHERE table_schema IN ('public','fc_')").fetchone()[0] == 15
    down = alembic(env, "downgrade", "base")
    assert down.returncode == 0, down.stderr[-2000:]
    with psycopg.connect(scratch_db) as c:
        left = c.execute("SELECT count(*) FROM information_schema.tables WHERE table_schema IN ('public','fc_') "
                         "AND table_name <> 'alembic_version'").fetchone()[0]
        assert left == 0
    again = alembic(env, "upgrade", "head")
    assert again.returncode == 0, again.stderr[-2000:]
