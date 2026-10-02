"""Service infrastructure: unit of work, shared context, audit helper and rejection logging.

Only services open transactions. A service method wraps its whole workflow in `unit_of_work`, so a failure
rolls everything back (including the audit row), and database errors surface as domain errors (409/422).
"""

from __future__ import annotations

import uuid
from collections.abc import Callable
from contextlib import contextmanager
from dataclasses import dataclass
from typing import TypeVar

from sqlalchemy.exc import DBAPIError
from sqlalchemy.orm import Session

from app.core.clock import Clock
from app.core.errors import translate_db_error
from app.db.models import Decision
from app.domain.ddi.params import DdiParams
from app.domain.errors import Forbidden, NotFound, StateConflict
from app.domain.nbe.params import NbeParams
from app.domain.permissions import Actor
from app.repositories import audit as audit_repo
from app.repositories import decisions as decisions_repo
from app.repositories.users import parse_uuid

T = TypeVar("T")


@contextmanager
def unit_of_work(session: Session):
    """BEGIN ... COMMIT around a workflow. Rolls back on any error and maps DB constraint errors to domain errors."""
    try:
        yield
        session.commit()
    except DBAPIError as exc:
        session.rollback()
        mapped = translate_db_error(exc)
        if mapped is not None:
            raise mapped from exc
        raise
    except BaseException:
        session.rollback()
        raise


@dataclass
class ServiceContext:
    session: Session
    clock: Clock
    ddi_params: DdiParams
    nbe_params: NbeParams


class BaseService:
    def __init__(self, ctx: ServiceContext):
        self.ctx = ctx
        self.session = ctx.session
        self.clock = ctx.clock

    # ---- loading
    def decision_or_404(self, actor: Actor, decision_id, *, lock: bool = False) -> Decision:
        did = parse_uuid(decision_id)
        row = (decisions_repo.lock_decision(self.session, did) if lock else decisions_repo.get_decision(self.session, did)) if did else None
        if row is None or str(row.org_id) != actor.org_id:
            raise NotFound("Decision not found.", detail={"decision_id": str(decision_id)})
        return row

    # ---- audit (exactly one row per event, same transaction, actor_id = the demo user)
    def audit(self, actor: Actor, action: str, entity_type: str, entity_id: uuid.UUID | None, decision: Decision, *,
              before: dict | None = None, after: dict | None = None) -> None:
        audit_repo.add_audit(self.session, org_id=decision.org_id, actor_id=uuid.UUID(actor.id), action=action,
                             entity_type=entity_type, entity_id=entity_id, decision_id=decision.id, before=before,
                             after=after, is_synthetic=decision.is_synthetic)

    # ---- transition rejection logging (decision-lifecycle.md LC-AC-2)
    def guarded(self, actor: Actor, decision_id, operation: str, fn: Callable[[], T]) -> T:
        """Run a lifecycle operation. A state conflict or permission refusal is rolled back and then logged as
        `transition.rejected` in its own small transaction before the error is re-raised."""
        try:
            with unit_of_work(self.session):
                return fn()
        except (StateConflict, Forbidden) as exc:
            self._log_rejection(actor, decision_id, operation, exc)
            raise

    def _log_rejection(self, actor: Actor, decision_id, operation: str, exc) -> None:
        did = parse_uuid(decision_id)
        if did is None:
            return
        try:
            with unit_of_work(self.session):
                decision = decisions_repo.get_decision(self.session, did)
                if decision is None or str(decision.org_id) != actor.org_id:
                    return
                self.audit(actor, "transition.rejected", "decision", decision.id, decision,
                           before={"lifecycle_stage": decision.lifecycle_stage},
                           after={"attempted": operation, "code": exc.code, "reason": exc.message})
        except Exception:  # noqa: BLE001  (logging a rejection must never mask the original error)
            self.session.rollback()
