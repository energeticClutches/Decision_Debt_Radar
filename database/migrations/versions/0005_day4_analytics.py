"""Day-4 analytics foundation: per-decision DQ checks, experiment inputs, evidence status and identity,
analysis hashes, decisions.expected_direction, read-only grant on metric_observations, active-evidence views

Revision ID: 0005
Revises: 0004
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from sqlfile import run_sql_file  # noqa: E402

revision = "0005"
down_revision = "0004"
branch_labels = None
depends_on = None


def upgrade() -> None:
    run_sql_file("0005_day4_analytics.sql")


def downgrade() -> None:
    run_sql_file("0005_day4_analytics_down.sql")
