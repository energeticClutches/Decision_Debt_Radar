"""SQLAlchemy models match the live schema (brief test 31) and the schema is never created from the models."""

from __future__ import annotations

import re
from pathlib import Path

import pytest
from sqlalchemy import inspect
from sqlalchemy.dialects.postgresql import ARRAY, ENUM
from sqlalchemy.types import (
    BOOLEAN,
    DATE,
    INTEGER,
    NUMERIC,
    SMALLINT,
    TEXT,
    TIMESTAMP,
    Boolean,
    Date,
    DateTime,
    Integer,
    Numeric,
    SmallInteger,
    Text,
    Uuid,
)

from app.db.models import Base

ROOT = Path(__file__).resolve().parents[2]


def family(t) -> str:
    """Normalize a (model or reflected) SQLAlchemy type to a comparable string."""
    if isinstance(t, ENUM):
        return f"enum:{t.name}"
    if isinstance(t, ARRAY):
        return f"{family(t.item_type)}[]"
    name = type(t).__name__.upper()
    if name == "JSONB":
        return "jsonb"
    if isinstance(t, (Uuid,)) or name == "UUID":
        return "uuid"
    if isinstance(t, (TEXT, Text)):
        return "text"
    if isinstance(t, (SMALLINT, SmallInteger)):
        return "smallint"
    if isinstance(t, (INTEGER, Integer)):
        return "integer"
    if isinstance(t, (NUMERIC, Numeric)):
        return "numeric"
    if isinstance(t, (BOOLEAN, Boolean)):
        return "boolean"
    if isinstance(t, (TIMESTAMP, DateTime)):
        return "timestamptz" if getattr(t, "timezone", False) else "timestamp"
    if isinstance(t, (DATE, Date)):
        return "date"
    return name.lower()


def test_31_models_match_live_schema_columns_types_and_nullability(engine):
    insp = inspect(engine)
    live_tables = {t for t in insp.get_table_names(schema="public") if t != "alembic_version"}
    model_tables = set(Base.metadata.tables)
    assert model_tables == live_tables and len(model_tables) == 25     # 22 + llm_classifications, syntheses, decision_briefs (0006)

    problems: list[str] = []
    for name, table in sorted(Base.metadata.tables.items()):
        live = {c["name"]: c for c in insp.get_columns(name, schema="public")}
        assert set(table.columns.keys()) == set(live), f"{name}: column sets differ: {set(table.columns.keys()) ^ set(live)}"
        pk_live = set(insp.get_pk_constraint(name, schema="public")["constrained_columns"])
        assert {c.name for c in table.primary_key.columns} == pk_live, f"{name}: primary key differs"
        for col in table.columns:
            lc = live[col.name]
            if family(col.type) != family(lc["type"]):
                problems.append(f"{name}.{col.name}: model {family(col.type)} vs live {family(lc['type'])}")
            if col.nullable != lc["nullable"]:
                problems.append(f"{name}.{col.name}: nullable model {col.nullable} vs live {lc['nullable']}")
    assert not problems, "\n".join(problems)


def test_31_migration_0004_columns_are_modelled(engine):
    cols = {c["name"]: c for c in inspect(engine).get_columns("decision_assessments")}
    for name in ("params_hash", "evidence_fingerprint", "as_of_date"):
        assert cols[name]["nullable"] is False
    for name in ("nbe_params_version", "nbe_params_hash"):
        assert cols[name]["nullable"] is True
    rec = {c["name"]: c for c in inspect(engine).get_columns("recommendations")}
    assert rec["blockers_resolved"]["nullable"] is False


def test_31_create_all_is_never_used():
    pattern = re.compile(r"\bcreate_all\s*\(")
    offenders = []
    for base in ("backend/app", "database", "agents", "data"):
        for path in (ROOT / base).rglob("*.py"):
            if ".venv" in path.parts:
                continue
            if pattern.search(path.read_text(encoding="utf-8")):
                offenders.append(str(path.relative_to(ROOT)))
    assert offenders == []
    assert pytest is not None
