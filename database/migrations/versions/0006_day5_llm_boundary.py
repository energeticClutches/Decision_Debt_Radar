"""Day-5 customer evidence, synthesis, review and brief: llm_classifications, syntheses, decision_briefs, evidence
proposed/rejected status and approval, customer-insight observed values, agent_runs LLM metadata

Revision ID: 0006
Revises: 0005
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from sqlfile import run_sql_file  # noqa: E402

revision = "0006"
down_revision = "0005"
branch_labels = None
depends_on = None


def upgrade() -> None:
    run_sql_file("0006_day5_llm_boundary.sql")


def downgrade() -> None:
    run_sql_file("0006_day5_llm_boundary_down.sql")
