"""Decision registry: create (canvas), edit canvas, confirm evidence base, read."""

from __future__ import annotations

import uuid
from datetime import date

from app.db.models import Decision
from app.domain import permissions as perm
from app.domain.canvas import canvas_warnings, validate_canvas
from app.domain.errors import InvalidInput, NotFound, StateConflict
from app.domain.permissions import Actor
from app.repositories import decisions as decisions_repo
from app.repositories import evidence as evidence_repo
from app.repositories.users import get_user, parse_uuid
from app.services.base import unit_of_work
from app.services.lifecycle import LifecycleHelpers, apply_transition

CANVAS_FIELDS = ("title", "description", "hypothesis", "success_metric_id", "decision_due_date", "risk_level",
                 "current_evidence_notes", "change_my_mind_criteria", "decision_type", "team_id", "owner_id")


def _snap(value):
    if isinstance(value, (uuid.UUID, date)):
        return str(value)
    return value


class DecisionService(LifecycleHelpers):
    # ---------------------------------------------------------------- read
    def get(self, actor: Actor, decision_id) -> Decision:
        return self.decision_or_404(actor, decision_id)

    def list(self, actor: Actor) -> list[Decision]:
        return decisions_repo.list_decisions(self.session, uuid.UUID(actor.org_id))

    # ---------------------------------------------------------------- create (canvas)
    def create(self, actor: Actor, fields: dict) -> tuple[Decision, list[dict]]:
        perm.authorize_role(actor, perm.CREATE_DECISION)
        with unit_of_work(self.session):
            validate_canvas(fields, decision_types=self.ctx.ddi_params.coverage_checklists, today=self.clock.today())
            metric_id = parse_uuid(fields.get("success_metric_id"))
            metric = decisions_repo.get_metric(self.session, metric_id) if metric_id else None
            if metric is None or str(metric.org_id) != actor.org_id:
                raise InvalidInput("The success metric does not exist (CV-3).", detail={"fields": {"success_metric_id": "unknown metric"}})
            team_id = parse_uuid(fields.get("team_id") or actor.team_id)
            owner_id = parse_uuid(fields.get("owner_id") or actor.id)
            team = decisions_repo.get_team(self.session, team_id) if team_id else None
            owner = get_user(self.session, owner_id) if owner_id else None
            if team is None or str(team.org_id) != actor.org_id:
                raise InvalidInput("A valid team is required.", detail={"fields": {"team_id": "unknown team"}})
            if owner is None or str(owner.org_id) != actor.org_id:
                raise InvalidInput("A valid owner is required.", detail={"fields": {"owner_id": "unknown user"}})
            decision = decisions_repo.add_decision(
                self.session, org_id=uuid.UUID(actor.org_id), team_id=team.id, owner_id=owner.id,
                title=fields["title"].strip(), description=fields["description"], hypothesis=fields["hypothesis"].strip(),
                success_metric_id=metric.id, decision_due_date=fields["decision_due_date"], risk_level=fields["risk_level"],
                current_evidence_notes=fields.get("current_evidence_notes"),
                change_my_mind_criteria=list(fields["change_my_mind_criteria"]), decision_type=fields["decision_type"],
                canvas_completed_at=self.clock.now(), is_synthetic=bool(metric.is_synthetic))
            self.audit(actor, "decision.created", "decision", decision.id, decision, before=None,
                       after={"lifecycle_stage": decision.lifecycle_stage, "title": decision.title,
                              "decision_type": decision.decision_type})
            warnings = canvas_warnings(decision.hypothesis, metric.name, metric.data_source_id is not None)
        return decision, warnings

    # ---------------------------------------------------------------- edit canvas (CV-7)
    def edit_canvas(self, actor: Actor, decision_id, changes: dict) -> Decision:
        perm.authorize_role(actor, perm.EDIT_CANVAS)
        with unit_of_work(self.session):
            decision = self.decision_or_404(actor, decision_id, lock=True)
            if decision.lifecycle_stage == "decided":
                raise StateConflict("The decision is decided and immutable in the MVP.")
            changes = {k: v for k, v in changes.items() if k in CANVAS_FIELDS and v is not None}
            if "success_metric_id" in changes:
                mid = parse_uuid(changes["success_metric_id"])
                metric = decisions_repo.get_metric(self.session, mid) if mid else None
                if metric is None or str(metric.org_id) != actor.org_id:
                    raise InvalidInput("The success metric does not exist (CV-3).")
                changes["success_metric_id"] = metric.id
            for key in ("team_id", "owner_id"):
                if key in changes:
                    changes[key] = parse_uuid(changes[key])
                    ok = decisions_repo.get_team(self.session, changes[key]) if key == "team_id" else get_user(self.session, changes[key])
                    if ok is None or str(ok.org_id) != actor.org_id:
                        raise InvalidInput(f"Unknown {key}.")
            due_changed = "decision_due_date" in changes and changes["decision_due_date"] != decision.decision_due_date
            validate_canvas(changes, decision_types=self.ctx.ddi_params.coverage_checklists, today=self.clock.today(),
                            check_due_date=due_changed)
            diff = {k: v for k, v in changes.items() if getattr(decision, k) != v}
            if not diff:
                return decision
            before = {k: _snap(getattr(decision, k)) for k in diff}
            stage_before = decision.lifecycle_stage
            locked = decision.canvas_locked_at is not None
            for k, v in diff.items():
                setattr(decision, k, v.strip() if isinstance(v, str) and k in ("title", "hypothesis") else v)
            self.session.flush()
            self.session.refresh(decision)          # the DB trigger may have marked the assessment stale
            self.audit(actor, "canvas.edited", "decision", decision.id, decision, before=before,
                       after={**{k: _snap(getattr(decision, k)) for k in diff}, "canvas_changed_after_assessment": locked})
            self.note_db_stale_return(actor, decision, stage_before, "canvas edited after the first assessment")
            return decision

    # ---------------------------------------------------------------- created -> evidence_gathered
    def confirm_evidence(self, actor: Actor, decision_id) -> Decision:
        def op() -> Decision:
            perm.authorize_role(actor, perm.CONFIRM_EVIDENCE)
            decision = self.decision_or_404(actor, decision_id, lock=True)
            if decision.lifecycle_stage != "created":
                raise StateConflict(
                    f"Evidence can only be confirmed from stage 'created' (the decision is '{decision.lifecycle_stage}').",
                    detail={"lifecycle_stage": decision.lifecycle_stage})
            metric = decisions_repo.get_metric(self.session, decision.success_metric_id)
            has_basis = metric.data_source_id is not None or bool(evidence_repo.list_evidence(self.session, decision.id))
            if not has_basis:
                raise StateConflict("Cannot confirm the evidence base: the success metric has no linked data source and no "
                                    "evidence item is linked (AC-20).")
            before = apply_transition(self.session, decision, "evidence_gathered")
            self.audit(actor, "decision.evidence_gathered", "decision", decision.id, decision,
                       before={"lifecycle_stage": before}, after={"lifecycle_stage": decision.lifecycle_stage})
            return decision
        return self.guarded(actor, decision_id, "confirm_evidence", op)


__all__ = ["CANVAS_FIELDS", "DecisionService", "NotFound"]
