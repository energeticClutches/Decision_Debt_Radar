"""Scope guard (brief test 32) and architecture boundary checks."""

from __future__ import annotations

import ast
from pathlib import Path

APP = Path(__file__).resolve().parents[2] / "backend" / "app"
# Day 4 (O3): sqlglot is allowed only in analytics/sql_guard.py. anthropic and agents stay forbidden everywhere.
FORBIDDEN_DAY_3 = {"anthropic", "sqlglot", "agents"}
SQLGLOT_ONLY_IN = "analytics/sql_guard.py"
FRAMEWORK_MODULES = {"sqlalchemy", "fastapi", "psycopg", "starlette", "alembic"}


def imported_modules(path: Path) -> set[str]:
    tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
    found: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            found.update(alias.name.split(".")[0] for alias in node.names)
        elif isinstance(node, ast.ImportFrom) and node.module and node.level == 0:
            found.add(node.module.split(".")[0])
    return found


def test_32_anthropic_sqlglot_and_agents_are_never_imported_under_backend_app():
    offenders = {}
    files = list(APP.rglob("*.py"))
    assert len(files) > 30                     # the scan really covers the backend
    for path in files:
        rel = path.relative_to(APP).as_posix()
        forbidden = FORBIDDEN_DAY_3 - ({"sqlglot"} if rel == SQLGLOT_ONLY_IN else set())
        bad = imported_modules(path) & forbidden
        if bad:
            offenders[rel] = sorted(bad)
    assert offenders == {}, offenders


def test_32_no_dynamic_import_of_forbidden_packages():
    for path in APP.rglob("*.py"):
        text = path.read_text(encoding="utf-8")
        for name in FORBIDDEN_DAY_3:
            assert f'import_module("{name}' not in text and f"__import__('{name}" not in text, (path, name)


def test_domain_layer_does_not_import_sqlalchemy_fastapi_or_psycopg():
    offenders = {}
    for path in (APP / "domain").rglob("*.py"):
        bad = imported_modules(path) & FRAMEWORK_MODULES
        if bad:
            offenders[str(path.relative_to(APP))] = sorted(bad)
    assert offenders == {}, offenders


def test_domain_never_reads_the_wall_clock():
    for path in (APP / "domain").rglob("*.py"):
        text = path.read_text(encoding="utf-8")
        assert "datetime.now" not in text and "date.today" not in text and "utcnow" not in text, path


def test_only_services_open_transactions():
    for sub in ("repositories", "domain", "api"):
        for path in (APP / sub).rglob("*.py"):
            text = path.read_text(encoding="utf-8")
            assert ".commit()" not in text and ".begin(" not in text and ".rollback()" not in text, path
