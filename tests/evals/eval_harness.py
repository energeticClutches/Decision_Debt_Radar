"""Run the evaluation outside pytest (scripts/eval_snapshot.py, scripts/eval_report.py) with the SAME rolled-back-transaction discipline as
the `session` fixture: nothing an evaluation does is ever committed to the demo database."""

from __future__ import annotations

import importlib.util
import os
import sys
from contextlib import contextmanager
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
HERE = Path(__file__).resolve().parent
BACKEND_TESTS = ROOT / "tests" / "backend"
LLM_FIXTURES = ROOT / "tests" / "fixtures" / "llm"


def setup_path() -> None:
    for p in (ROOT / "backend", ROOT, HERE, BACKEND_TESTS, LLM_FIXTURES):
        if str(p) not in sys.path:
            sys.path.insert(0, str(p))
    os.environ.setdefault("DDR_LLM_MODE", "off")      # the suite never calls a live model


def _database_url() -> str:
    url = os.environ.get("DATABASE_URL")
    if not url:
        env = ROOT / ".env"
        if env.exists():
            for line in env.read_text(encoding="utf-8").splitlines():
                if line.startswith("DATABASE_URL="):
                    url = line.split("=", 1)[1].strip()
    if not url:
        from app.core.config import get_settings
        url = get_settings().database_url
    return url.replace("postgresql://", "postgresql+psycopg://", 1) if url.startswith("postgresql://") else url


@contextmanager
def rolled_back_session():
    """Yield (session, seed) inside an outer transaction that is ALWAYS rolled back."""
    setup_path()
    from sqlalchemy import create_engine
    from sqlalchemy.orm import Session
    spec = importlib.util.spec_from_file_location("ddr_backend_test_conftest_h", BACKEND_TESTS / "conftest.py")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    engine = create_engine(_database_url(), future=True)
    conn = engine.connect()
    outer = conn.begin()
    session = Session(bind=conn, join_transaction_mode="create_savepoint", expire_on_commit=False)
    try:
        yield session, mod.Seed(session)
    finally:
        session.close()
        outer.rollback()
        conn.close()
        engine.dispose()
