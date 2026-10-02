"""reporting views, fc_ analytical views, read-only role

Revision ID: 0003
Revises: 0002
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from sqlfile import run_sql_file  # noqa: E402

revision = "0003"
down_revision = "0002"
branch_labels = None
depends_on = None


def upgrade() -> None:
    run_sql_file("0003_views_and_roles.sql")


def downgrade() -> None:
    run_sql_file("0003_views_and_roles_down.sql")
