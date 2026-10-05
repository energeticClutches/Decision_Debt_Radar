"""Role permission matrix (brief section 3.8, PRD section 3, decision-lifecycle.md section 4).

Demo identity only. This is a role switcher, not authentication (R14). The server reads the role and team of
the demo user from the database.
"""

from __future__ import annotations

from dataclasses import dataclass

from app.domain.errors import Forbidden

CREATE_DECISION = "create_decision"
EDIT_CANVAS = "edit_canvas"
CONFIRM_EVIDENCE = "confirm_evidence"
ADD_EVIDENCE = "add_evidence"
RUN_ASSESSMENT = "run_assessment"
HUMAN_REVIEW = "human_review"
VALIDATE = "validate"
RECORD_DECISION = "record_decision"
UPDATE_DQ = "update_dq_check"
UPDATE_RECOMMENDATION = "update_recommendation"
APPROVE_EVIDENCE = "approve_evidence"            # Day 5: approve or reject a proposed (decision, theme) customer evidence item
RUN_SYNTHESIS = "run_synthesis"                  # Day 5: re-synthesis (a new version and a new agent review)
CREATE_BRIEF = "create_brief"                    # Day 5: Decision Brief or Gated Evidence Summary

ROLE_ACTIONS: dict[str, frozenset[str]] = {
    CREATE_DECISION: frozenset({"pm", "ba"}),
    EDIT_CANVAS: frozenset({"pm", "ba"}),
    CONFIRM_EVIDENCE: frozenset({"pm", "ba", "product_analyst"}),
    ADD_EVIDENCE: frozenset({"pm", "ba", "product_analyst"}),
    RUN_ASSESSMENT: frozenset({"pm", "ba", "product_analyst"}),
    HUMAN_REVIEW: frozenset({"pm", "ba", "dept_leader", "executive"}),
    VALIDATE: frozenset({"pm", "ba", "dept_leader", "executive"}),
    RECORD_DECISION: frozenset({"dept_leader", "executive"}),   # plus the decision owner, whatever their role
    UPDATE_DQ: frozenset({"product_analyst", "ba"}),
    UPDATE_RECOMMENDATION: frozenset({"pm", "ba", "product_analyst"}),
    APPROVE_EVIDENCE: frozenset({"ba", "product_analyst"}),
    RUN_SYNTHESIS: frozenset({"pm", "ba"}),
    CREATE_BRIEF: frozenset({"pm", "ba"}),
}

# Actions where a department leader may act only on decisions of their own team (user.team_id = decision.team_id).
LEADER_OWN_TEAM_ONLY = frozenset({VALIDATE, RECORD_DECISION})
# The decision owner may always record the decision, whatever their role.
OWNER_ALSO_ALLOWED = frozenset({RECORD_DECISION})


@dataclass(frozen=True)
class Actor:
    id: str
    org_id: str
    team_id: str | None
    role: str
    name: str = ""


def authorize_role(actor: Actor, action: str) -> None:
    """Role-only check (no decision needed)."""
    allowed = ROLE_ACTIONS[action]
    if actor.role not in allowed:
        raise Forbidden(f"Role '{actor.role}' may not perform '{action}'.",
                        detail={"role": actor.role, "action": action, "allowed_roles": sorted(allowed)})


def authorize_on_decision(actor: Actor, action: str, *, decision_team_id: str, decision_owner_id: str) -> None:
    """Role check plus the ownership rules (leader own team; the owner may record their own decision)."""
    if action in OWNER_ALSO_ALLOWED and actor.id == decision_owner_id:
        return
    authorize_role(actor, action)
    if action in LEADER_OWN_TEAM_ONLY and actor.role == "dept_leader" and actor.team_id != decision_team_id:
        raise Forbidden("A department leader may act only on decisions of their own team.",
                        detail={"role": actor.role, "action": action})
