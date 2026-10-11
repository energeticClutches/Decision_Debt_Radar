"""Deploy compatibility: membership of ddr_readonly (with SET) for the connecting role, so SET ROLE works for a non-superuser
database owner (Neon). No schema change, no semantic change.

Revision ID: 0007
Revises: 0006
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from sqlfile import run_sql_file  # noqa: E402

revision = "0007"
down_revision = "0006"
branch_labels = None
depends_on = None


def upgrade() -> None:
    run_sql_file("0007_deploy_compat.sql")


def downgrade() -> None:
    run_sql_file("0007_deploy_compat_down.sql")
