"""fc_ schema: synthetic FitConnect demo data tables

Revision ID: 0002
Revises: 0001
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from sqlfile import run_sql_file  # noqa: E402

revision = "0002"
down_revision = "0001"
branch_labels = None
depends_on = None


def upgrade() -> None:
    run_sql_file("0002_fc_schema.sql")


def downgrade() -> None:
    run_sql_file("0002_fc_schema_down.sql")
