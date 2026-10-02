"""Evidence register: add and change evidence items (stale handling after assessment)."""

from __future__ import annotations

import uuid
from datetime import date

from app.db.models import Evidence
from app.domain import permissions as perm
from app.domain.canvas import validate_evidence
from app.domain.errors import InvalidInput, NotFound, StateConflict
from app.domain.permissions import Actor
from app.repositories import evidence as evidence_repo
from app.repositories.users import parse_uuid
from app.services.base import unit_of_work
from app.services.lifecycle import LifecycleHelpers

EVIDENCE_FIELDS = ("evidence_source_id", "evidence_type", "summary", "stance", "strength_grade", "observed_start",
                   "observed_end", "n_sample", "effect_size", "ci_low", "ci_high", "metric_id", "experiment_id", "insight_id")
_LINKS = ("evidence_source_id", "metric_id", "experiment_id", "insight_id")


def _snap(v):
    if isinstance(v, (uuid.UUID, date)):
        return str(v)
    if hasattr(v, "as_tuple"):          # Decimal
        return float(v)
    return v


class EvidenceService(LifecycleHelpers):
    def list(self, actor: Actor, decision_id) -> list[Evidence]:
        decision = self.decision_or_404(actor, decision_id)
        return evidence_repo.list_evidence(self.session, decision.id)

    def _check_links(self, actor: Actor, decision, fields: dict) -> dict:
        out = dict(fields)
        for key in _LINKS:
            if out.get(key) is None:
                continue
            out[key] = parse_uuid(out[key])
            if out[key] is None:
                raise InvalidInput(f"{key} is not a valid id.", detail={"fields": {key: "invalid id"}})
        src = out.get("evidence_source_id")
        if "evidence_source_id" in out:
            row = evidence_repo.get_evidence_source(self.session, src) if src else None
            if row is None or str(row.org_id) != actor.org_id:
                raise InvalidInput("Unknown evidence source.", detail={"fields": {"evidence_source_id": "unknown"}})
        if out.get("metric_id"):
            m = evidence_repo.get_metric(self.session, out["metric_id"])
            if m is None or str(m.org_id) != actor.org_id:
                raise InvalidInput("Unknown metric.", detail={"fields": {"metric_id": "unknown"}})
        if out.get("experiment_id"):
            e = evidence_repo.get_experiment(self.session, out["experiment_id"])
            if e is None or str(e.org_id) != actor.org_id or (e.decision_id is not None and e.decision_id != decision.id):
                raise InvalidInput("Unknown experiment for this decision.", detail={"fields": {"experiment_id": "unknown"}})
        if out.get("insight_id"):
            i = evidence_repo.get_insight(self.session, out["insight_id"])
            if i is None or str(i.org_id) != actor.org_id or (i.decision_id is not None and i.decision_id != decision.id):
                raise InvalidInput("Unknown customer insight for this decision.", detail={"fields": {"insight_id": "unknown"}})
        return out

    def add(self, actor: Actor, decision_id, fields: dict) -> Evidence:
        perm.authorize_role(actor, perm.ADD_EVIDENCE)
        with unit_of_work(self.session):
            decision = self.decision_or_404(actor, decision_id, lock=True)
            if decision.lifecycle_stage == "decided":
                raise StateConflict("The decision is decided: evidence can no longer be added.")
            data = {k: fields.get(k) for k in EVIDENCE_FIELDS}
            validate_evidence(data)
            data = self._check_links(actor, decision, data)
            ev = evidence_repo.add_evidence(self.session, decision_id=decision.id, created_by="user",
                                            is_synthetic=decision.is_synthetic, **data)
            self.audit(actor, "evidence.added", "evidence", ev.id, decision, before=None,
                       after={"evidence_type": ev.evidence_type, "stance": ev.stance, "strength_grade": ev.strength_grade})
            self.mark_stale_if_needed(actor, decision, "evidence added after the assessment")
            return ev

    def update(self, actor: Actor, decision_id, evidence_id, changes: dict) -> Evidence:
        perm.authorize_role(actor, perm.ADD_EVIDENCE)
        with unit_of_work(self.session):
            decision = self.decision_or_404(actor, decision_id, lock=True)
            if decision.lifecycle_stage == "decided":
                raise StateConflict("The decision is decided: evidence can no longer be changed.")
            eid = parse_uuid(evidence_id)
            ev = evidence_repo.get_evidence(self.session, eid) if eid else None
            if ev is None or ev.decision_id != decision.id:
                raise NotFound("Evidence item not found for this decision.")
            changes = {k: v for k, v in changes.items() if k in EVIDENCE_FIELDS}
            merged = {k: getattr(ev, k) for k in EVIDENCE_FIELDS} | changes
            validate_evidence({k: (float(v) if hasattr(v, "as_tuple") else v) for k, v in merged.items()})
            changes = self._check_links(actor, decision, changes)
            before = {k: _snap(getattr(ev, k)) for k in changes}
            for k, v in changes.items():
                setattr(ev, k, v)
            self.session.flush()
            self.session.refresh(ev)
            self.audit(actor, "evidence.updated", "evidence", ev.id, decision, before=before,
                       after={k: _snap(getattr(ev, k)) for k in changes})
            self.mark_stale_if_needed(actor, decision, "evidence changed after the assessment")
            return ev
