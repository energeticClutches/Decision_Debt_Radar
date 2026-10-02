"""FastAPI dependencies: session, clock, parameters, demo identity (role switcher) and services.

Demo identity (R14): the header `X-Demo-User: <seeded user uuid>` selects the acting user. The server reads
the role and team of that user from the database. This is a demo role switcher, NOT authentication.
"""

from __future__ import annotations

from collections.abc import Iterator

from fastapi import Depends, Header
from sqlalchemy.orm import Session

from app.core.clock import Clock, FixedClock, SystemClock
from app.core.config import get_settings
from app.core.params import get_ddi_params, get_nbe_params
from app.db.session import session_scope
from app.domain.errors import Unauthorized
from app.domain.permissions import Actor
from app.repositories.users import get_user, to_actor
from app.services import (
    AssessmentService,
    AuditService,
    DecisionRecordService,
    DecisionService,
    DqService,
    EvidenceService,
    RecommendationService,
    ReviewService,
    ServiceContext,
)

DEMO_HEADER = "X-Demo-User"


def get_session() -> Iterator[Session]:
    yield from session_scope()


def get_clock() -> Clock:
    fixed = get_settings().ddr_as_of_date
    return FixedClock(fixed) if fixed else SystemClock()


def get_actor(x_demo_user: str | None = Header(default=None, alias=DEMO_HEADER),
              session: Session = Depends(get_session)) -> Actor:
    if not x_demo_user:
        raise Unauthorized(f"Demo identity missing: send the {DEMO_HEADER} header with a seeded user id.")
    user = get_user(session, x_demo_user)
    if user is None:
        raise Unauthorized("Demo identity unknown: the user id is not a seeded demo user.")
    return to_actor(user)


def get_ctx(session: Session = Depends(get_session), clock: Clock = Depends(get_clock)) -> ServiceContext:
    return ServiceContext(session=session, clock=clock, ddi_params=get_ddi_params(), nbe_params=get_nbe_params())


def decision_service(ctx: ServiceContext = Depends(get_ctx)) -> DecisionService:
    return DecisionService(ctx)


def evidence_service(ctx: ServiceContext = Depends(get_ctx)) -> EvidenceService:
    return EvidenceService(ctx)


def assessment_service(ctx: ServiceContext = Depends(get_ctx)) -> AssessmentService:
    return AssessmentService(ctx)


def review_service(ctx: ServiceContext = Depends(get_ctx)) -> ReviewService:
    return ReviewService(ctx)


def record_service(ctx: ServiceContext = Depends(get_ctx)) -> DecisionRecordService:
    return DecisionRecordService(ctx)


def recommendation_service(ctx: ServiceContext = Depends(get_ctx)) -> RecommendationService:
    return RecommendationService(ctx)


def dq_service(ctx: ServiceContext = Depends(get_ctx)) -> DqService:
    return DqService(ctx)


def audit_service(ctx: ServiceContext = Depends(get_ctx)) -> AuditService:
    return AuditService(ctx)
