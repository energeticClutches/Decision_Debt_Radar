"""CSV loading foundation (CSV-only ingestion, PRD ADR-008).

Validates the header against the expected column list, streams the file through PostgreSQL
COPY, and relies on the database constraints (including is_synthetic CHECKs on fc_ tables) to
reject bad rows. No transformation happens here.
"""

from __future__ import annotations

import re
from pathlib import Path

import psycopg

_IDENT = re.compile(r"^[a-z_][a-z0-9_]*(\.[a-z_][a-z0-9_]*)?$")
_CHUNK = 1 << 20


def to_conninfo(database_url: str) -> str:
    """Convert a SQLAlchemy-style URL (postgresql+psycopg://...) or a provider URL (postgres://...) to a libpq URL."""
    url = database_url.strip()
    if url.startswith("postgres://"):
        return "postgresql://" + url[len("postgres://"):]
    return url.replace("postgresql+psycopg://", "postgresql://", 1)


def read_header(path: Path) -> list[str]:
    with path.open("r", encoding="utf-8", newline="") as f:
        return f.readline().rstrip("\r\n").split(",")


def load_csv(conn: psycopg.Connection, table: str, path: Path, columns: list[str]) -> int:
    """COPY a CSV into `table`. Returns the number of rows loaded."""
    if not _IDENT.match(table) or not all(_IDENT.match(c) for c in columns):
        raise ValueError(f"unsafe identifier in {table!r} / {columns!r}")
    header = read_header(path)
    if header != columns:
        raise ValueError(f"{path.name}: header {header} does not match expected columns {columns}")
    sql = f"COPY {table} ({', '.join(columns)}) FROM STDIN WITH (FORMAT csv, HEADER true)"
    with conn.cursor() as cur, path.open("rb") as f:
        with cur.copy(sql) as copy:
            while chunk := f.read(_CHUNK):
                copy.write(chunk)
        return cur.rowcount
