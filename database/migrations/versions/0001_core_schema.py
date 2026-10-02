"""core schema: enums, 22 core tables, constraints, lifecycle guards

Revision ID: 0001
Revises:
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from sqlfile import run_sql_file  # noqa: E402

revision = "0001"
down_revision = None
branch_labels = None
depends_on = None


def upgrade() -> None:
    run_sql_file("0001_core_schema.sql")


def downgrade() -> None:
    run_sql_file("0001_core_schema_down.sql")
