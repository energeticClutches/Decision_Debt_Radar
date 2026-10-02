"""Read-only execution of catalogue SQL (docs/day-4-implementation-brief.md section 9).

  1. The template goes through the SQL guard (parser: one SELECT, allow-listed tables, LIMIT, no denied functions).
  2. It then runs in its OWN transaction on its OWN connection (never the caller's session) with
       SET TRANSACTION READ ONLY, SET LOCAL ROLE ddr_readonly, SET LOCAL statement_timeout, SET LOCAL TIME ZONE 'UTC'.
     The role is the real security boundary: it has SELECT on the allow-listed views and public.metric_observations
     only, so a mutation or a read of any other table that slipped past the parser is still rejected by the database.
  3. Parameters are bound by the driver, never interpolated.

The executor accepts only a QueryTemplate from the catalogue (app.analytics.queries). There is no free-form path.
"""

from __future__ import annotations

import re
from collections.abc import Mapping
from typing import Any

from sqlalchemy import Engine, text

from app.analytics.queries import QueryTemplate
from app.analytics.sql_guard import DEFAULT_MAX_ROWS, validate_select

READONLY_ROLE = "ddr_readonly"
_TIMEOUT = re.compile(r"^\d+(ms|s|min)$")


class ReadOnlyExecutor:
    def __init__(self, engine: Engine | None = None, *, max_rows: int = DEFAULT_MAX_ROWS, statement_timeout: str = "30s"):
        if not _TIMEOUT.match(statement_timeout):
            raise ValueError(f"invalid statement timeout {statement_timeout!r}")
        if engine is None:
            from app.db.session import get_engine
            engine = get_engine()
        self.engine = engine
        self.max_rows = max_rows
        self.statement_timeout = statement_timeout

    def run(self, template: QueryTemplate, params: Mapping[str, Any] | None = None) -> list[dict[str, Any]]:
        if not isinstance(template, QueryTemplate):
            raise TypeError("only catalogue QueryTemplate objects can be executed (no free-form SQL)")
        params = dict(params or {})
        missing, extra = set(template.params) - set(params), set(params) - set(template.params)
        if missing or extra:
            raise ValueError(f"{template.name}: parameters do not match the template (missing {sorted(missing)}, "
                             f"unexpected {sorted(extra)})")
        guarded = validate_select(template.sql, max_rows=self.max_rows)
        return self._execute(template.sql, params, guarded.limit)

    def _execute(self, sql: str, params: Mapping[str, Any], limit: int) -> list[dict[str, Any]]:
        """Run already-validated SQL under the read-only role. Also used directly by tests to prove that the database
        itself rejects what the parser would have refused."""
        with self.engine.connect() as conn:
            with conn.begin():
                conn.exec_driver_sql("SET TRANSACTION READ ONLY")
                conn.exec_driver_sql(f"SET LOCAL ROLE {READONLY_ROLE}")
                conn.exec_driver_sql(f"SET LOCAL statement_timeout = '{self.statement_timeout}'")
                conn.exec_driver_sql("SET LOCAL TIME ZONE 'UTC'")
                result = conn.execute(text(sql), dict(params))
                return [dict(r) for r in result.mappings().fetchmany(limit + 1)]
