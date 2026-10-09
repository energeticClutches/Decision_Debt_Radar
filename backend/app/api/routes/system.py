from __future__ import annotations

from fastapi import APIRouter, Depends
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.config import get_settings
from app.core.deps import get_actor, get_session, readmodel_service
from app.db.models import Team
from app.domain.permissions import Actor
from app.repositories import users as users_repo
from app.schemas.responses import MetricOut, UserOut, user_out
from app.services import ReadModelService

router = APIRouter()


@router.get("/health", tags=["system"])
def health() -> dict[str, str]:
    settings = get_settings()
    return {
        "status": "ok",
        "service": "decision-debt-radar-api",
        "env": settings.app_env,
        "ddi_params_version": settings.ddi_params_version,
        "nbe_params_version": settings.nbe_params_version,
        "llm_mode": settings.ddr_llm_mode,        # live | replay | off (D6-01); the UI shows a chip when it is replay
    }


@router.get("/users", tags=["demo identity"], response_model=list[UserOut])
def list_users(session: Session = Depends(get_session)):
    """The role-switcher list. Demo identity only: no authentication."""
    teams = {t.id: t.name for t in session.scalars(select(Team))}
    return [user_out(u, teams.get(u.team_id)) for u in users_repo.list_users(session)]


@router.get("/me", tags=["demo identity"], response_model=UserOut)
def me(actor: Actor = Depends(get_actor), session: Session = Depends(get_session)):
    user = users_repo.get_user(session, actor.id)
    team = session.get(Team, user.team_id) if user.team_id else None
    return user_out(user, team.name if team else None)


@router.get("/metrics", tags=["reference"], response_model=list[MetricOut])
def list_metrics(actor: Actor = Depends(get_actor), rm: ReadModelService = Depends(readmodel_service)):
    """N6: the metric definitions of the organisation (read-only). The canvas form uses them to pick the success metric."""
    return [{"id": str(x.id), "name": x.name, "definition": x.definition, "unit": x.unit, "grain": x.grain} for x in rm.metrics(actor)]
