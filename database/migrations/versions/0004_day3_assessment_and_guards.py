"""Day-3 invariants: assessment metadata, blockers_resolved, canvas-edit stale rule, decided-write guards

Revision ID: 0004
Revises: 0003
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from sqlfile import run_sql_file  # noqa: E402

revision = "0004"
down_revision = "0003"
branch_labels = None
depends_on = None


def upgrade() -> None:
    run_sql_file("0004_day3_assessment_and_guards.sql")


def downgrade() -> None:
    run_sql_file("0004_day3_assessment_and_guards_down.sql")
