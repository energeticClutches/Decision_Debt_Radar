from __future__ import annotations

import uuid

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.db.models import User
from app.domain.permissions import Actor


def parse_uuid(value) -> uuid.UUID | None:
    if isinstance(value, uuid.UUID):
        return value
    try:
        return uuid.UUID(str(value))
    except (ValueError, AttributeError, TypeError):
        return None


def get_user(session: Session, user_id) -> User | None:
    uid = parse_uuid(user_id)
    return session.get(User, uid) if uid else None


def list_users(session: Session) -> list[User]:
    return list(session.scalars(select(User).order_by(User.role, User.name)))


def to_actor(user: User) -> Actor:
    return Actor(id=str(user.id), org_id=str(user.org_id), team_id=str(user.team_id) if user.team_id else None,
                 role=user.role, name=user.name)
