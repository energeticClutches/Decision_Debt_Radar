"""Storing and reconciling DQ findings (D4-03, D4-04). A re-run updates the row of the same (decision, check_key) in place.

| current status | re-run result                  | action                                                                   |
| open           | defect present (any severity)  | stays open, severity updated                                             |
| open           | defect gone (pass)             | stays open with severity pass; audited dq.auto_cleared_pending_review    |
| accepted       | same or lower severity         | stays accepted                                                           |
| accepted       | worse                          | reopened as open + audit                                                 |
| resolved       | defect still present           | reopened as open + audit                                                 |
| resolved       | defect gone                    | stays resolved                                                           |

Only a human resolves a check: a pass never closes an open check. Pass rows never block. Automatic changes are audited with
actor_type = 'system'. This module never commits (the service layer does).
"""

from __future__ import annotations

import uuid
from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field
from datetime import datetime
from decimal import Decimal

from sqlalchemy.orm import Session

from app.analytics.dq import SEVERITY_ORDER, DqFinding
from app.db.models import Decision, DqCheck
from app.repositories import audit as audit_repo
from app.repositories import dq as dq_repo


@dataclass
class ReconcileSummary:
    created: int = 0
    unchanged: int = 0
    updated: int = 0
    reopened: list[str] = field(default_factory=list)
    auto_cleared: list[str] = field(default_factory=list)
    severity_changed: list[str] = field(default_factory=list)

    @property
    def status_changed(self) -> bool:
        """A status change (a reopen) after an assessment marks it stale (the Day-3 rule)."""
        return bool(self.reopened)

    def as_dict(self) -> dict:
        return {"created": self.created, "updated": self.updated, "unchanged": self.unchanged, "reopened": sorted(self.reopened),
                "auto_cleared_pending_review": sorted(self.auto_cleared), "severity_changed": sorted(self.severity_changed)}


def check_key(data_source_id: uuid.UUID | str, finding: DqFinding) -> str:
    return f"{data_source_id}|{finding.check_type}|{finding.target}"


def _audit(session: Session, decision: Decision, action: str, row: DqCheck, before: dict, after: dict) -> None:
    audit_repo.add_audit(session, org_id=decision.org_id, actor_id=None, actor_type="system", action=action, entity_type="dq_check",
                         entity_id=row.id, decision_id=decision.id, before=before, after={**after, "check_key": row.check_key},
                         is_synthetic=decision.is_synthetic)


def _numeric(x: float | None) -> Decimal | None:
    """10 decimal places, as a Decimal, so a re-run of unchanged data compares equal to the stored value."""
    return None if x is None else Decimal(format(round(float(x), 10), ".10f"))


def reconcile(session: Session, decision: Decision, findings: Sequence[DqFinding], *, data_source_ids: Mapping[str, uuid.UUID],
              now: datetime) -> ReconcileSummary:
    existing = dq_repo.checks_by_key(session, decision.id)
    out = ReconcileSummary()
    for f in findings:
        ds_id = data_source_ids[f.data_source_ref]
        key = check_key(ds_id, f)
        fields = dict(check_type=f.check_type, data_source_id=ds_id, target=f.target, observed_value=_numeric(f.observed_value),
                      threshold=_numeric(f.threshold), severity=f.severity, finding=f.finding, source_snapshot=f.snapshot,
                      affects_success_metric=f.in_lineage, affects_metric_id=decision.success_metric_id if f.in_lineage else None)
        row = existing.get(key)
        if row is None:
            dq_repo.add_check(session, decision_id=decision.id, assessment_id=None, check_key=key, status="open",
                              is_synthetic=decision.is_synthetic, last_run_at=now, **fields)
            out.created += 1
            continue
        old_sev, new_sev, status = row.severity, f.severity, row.status
        changed = {k: v for k, v in fields.items() if getattr(row, k) != v}
        before = {"status": status, "severity": old_sev}
        if status == "open":
            if new_sev == "pass" and old_sev != "pass":
                _audit(session, decision, "dq.auto_cleared_pending_review", row, before, {"status": "open", "severity": "pass"})
                out.auto_cleared.append(key)
            elif new_sev != old_sev:
                _audit(session, decision, "dq.severity_changed", row, before, {"status": "open", "severity": new_sev})
                out.severity_changed.append(key)
        elif (status == "accepted" and SEVERITY_ORDER[new_sev] > SEVERITY_ORDER[old_sev]) or (status == "resolved" and new_sev != "pass"):
            changed.update(status="open", resolved_by=None, resolved_at=None)
            _audit(session, decision, "dq.reopened", row, before, {"status": "open", "severity": new_sev})
            out.reopened.append(key)
        row.last_run_at = now
        if changed:
            for k, v in changed.items():
                setattr(row, k, v)
            out.updated += 1
        else:
            out.unchanged += 1
        session.flush()
    session.flush()
    return out
