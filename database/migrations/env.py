"""Alembic environment.

The connection string comes from DATABASE_URL (environment or the repository's .env file).
Migrations are SQL files in database/sql/ executed by the revision scripts, so the schema,
constraints, triggers and views are explicit and reviewable. Models arrive with the API (Day 3).
"""

import os
from pathlib import Path

from alembic import context
from sqlalchemy import create_engine, pool

config = context.config
target_metadata = None


def _database_url() -> str | None:
    url = os.environ.get("DATABASE_URL")
    if url:
        return url
    env_file = Path(__file__).resolve().parents[2] / ".env"
    if env_file.exists():
        for line in env_file.read_text(encoding="utf-8").splitlines():
            line = line.strip()
            if line.startswith("DATABASE_URL="):
                return line.split("=", 1)[1].strip()
    return None


def _normalise(url: str | None) -> str | None:
    """Accept a provider URL (Neon: postgres://...?sslmode=require) and use the psycopg 3 driver, like the application does."""
    if not url:
        return url
    url = url.strip()
    for prefix in ("postgres://", "postgresql://"):
        if url.startswith(prefix):
            return "postgresql+psycopg://" + url[len(prefix):]
    return url


DATABASE_URL = _normalise(_database_url())


def run_migrations_offline() -> None:
    context.configure(url=DATABASE_URL, target_metadata=target_metadata, literal_binds=True)
    with context.begin_transaction():
        context.run_migrations()


def run_migrations_online() -> None:
    if not DATABASE_URL:
        raise RuntimeError("DATABASE_URL is not set (see .env.example)")
    engine = create_engine(DATABASE_URL, poolclass=pool.NullPool)
    with engine.connect() as connection:
        context.configure(connection=connection, target_metadata=target_metadata)
        with context.begin_transaction():
            context.run_migrations()


if context.is_offline_mode():
    run_migrations_offline()
else:
    run_migrations_online()
