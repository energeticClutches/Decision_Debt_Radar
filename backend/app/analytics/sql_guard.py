"""SQL guard (docs/day-4-implementation-brief.md section 9). The ONLY module under backend/app that imports sqlglot.

Defence in depth: the database role (ddr_readonly, SELECT on the allow-listed views only, read-only transaction,
statement timeout) is the real security boundary. This parser rejects, before anything reaches the database:

  * anything that is not exactly one SELECT statement (CTEs allowed, data-modifying CTEs rejected)
  * DML and DDL, SELECT INTO, locking clauses, COPY, SET, transaction control and other commands
  * table-valued functions and every table that is not allow-listed (the eight fc_.v_* views and
    public.metric_observations, both schema-qualified). CTE names are not tables
  * calls to functions on the deny list (pg_sleep, dblink*, lo_*, pg_read_file and similar)
  * a missing LIMIT, or a LIMIT above max_rows

All Day-4 analysis SQL comes from the parameterised template catalogue (app.analytics.queries) and goes through this
guard. There is no LLM-generated SQL. Rejections raise SqlRejected and are logged.
"""

from __future__ import annotations

import logging
import re
from dataclasses import dataclass

import sqlglot
from sqlglot import exp
from sqlglot.errors import SqlglotError

logger = logging.getLogger("app.analytics.sql_guard")

DEFAULT_MAX_ROWS = 100_000

ALLOWED_TABLES: frozenset[str] = frozenset({
    "fc_.v_users", "fc_.v_events", "fc_.v_subscriptions", "fc_.v_feedback", "fc_.v_experiment_assignments",
    "fc_.v_experiment_outcomes", "fc_.v_ai_inference_costs", "fc_.v_pricing_model_inputs",
    "public.metric_observations",
})

DENIED_FUNCTION_PATTERNS: tuple[re.Pattern[str], ...] = tuple(re.compile(p) for p in (
    r"pg_sleep.*", r"dblink.*", r"lo_.*", r"pg_read_.*", r"pg_ls_.*", r"pg_stat_file", r"pg_.*_file.*", r"pg_file_.*",
    r"pg_advisory_.*", r"pg_terminate_backend", r"pg_cancel_backend", r"pg_reload_conf", r"pg_rotate_logfile",
    r"pg_logical_.*", r"pg_replication_.*", r"pg_create_.*", r"pg_drop_.*", r"pg_switch_wal", r"pg_start_backup",
    r"pg_stop_backup", r"set_config", r"current_setting", r"nextval", r"setval", r"currval", r"lastval",
    r"txid_.*", r"query_to_xml.*", r"table_to_xml.*", r"cursor_to_xml.*", r"database_to_xml.*", r"schema_to_xml.*",
    r"xpath.*", r"copy_.*", r"load_extension", r"pg_notify", r"pg_import_system_collations",
    # set-returning / resource-amplifying functions that no Day-4 template needs
    r"generate_series", r"generate_subscripts", r"unnest", r"repeat",
))

# sqlglot node classes that must never appear anywhere in the tree (data-modifying or non-SELECT constructs).
_FORBIDDEN_NODE_NAMES = (
    "Insert", "Update", "Delete", "Merge", "Create", "Drop", "Alter", "AlterTable", "AlterColumn", "Command", "Copy",
    "TruncateTable", "Grant", "Revoke", "Set", "SetItem", "Pragma", "Transaction", "Commit", "Rollback", "Analyze",
    "Execute", "Use", "Show", "Describe", "Refresh", "Kill", "Declare", "Lock", "Into", "LoadData", "Attach", "Detach",
)
_FORBIDDEN_NODES: tuple[type, ...] = tuple(getattr(exp, n) for n in _FORBIDDEN_NODE_NAMES if hasattr(exp, n))


class SqlRejected(Exception):
    """The statement is not allowed. `reason` is a short machine-readable explanation."""

    def __init__(self, reason: str, sql: str = ""):
        super().__init__(reason)
        self.reason = reason
        self.sql = sql


@dataclass(frozen=True)
class GuardedSql:
    sql: str
    tables: tuple[str, ...]
    functions: tuple[str, ...]
    limit: int


def _reject(reason: str, sql: str):
    logger.warning("sql rejected: %s | %.200s", reason, " ".join(sql.split()))
    raise SqlRejected(reason, sql)


def _function_name(node: exp.Func) -> str:
    if isinstance(node, exp.Anonymous):
        name = node.name
    else:
        name = node.sql_name()
    return (name or "").lower().split(".")[-1]


def validate_select(sql: str, *, max_rows: int = DEFAULT_MAX_ROWS,
                    allowed_tables: frozenset[str] | set[str] = ALLOWED_TABLES) -> GuardedSql:
    """Return the facts about an accepted statement, or raise SqlRejected."""
    if not isinstance(sql, str) or not sql.strip():
        _reject("empty statement", str(sql))
    try:
        statements = [s for s in sqlglot.parse(sql, read="postgres") if s is not None]
    except SqlglotError as exc:
        _reject(f"unparseable SQL: {type(exc).__name__}", sql)
    if len(statements) != 1:
        _reject(f"exactly one statement is allowed (found {len(statements)})", sql)
    # Belt and braces against a parser differential (sqlglot reading one statement where PostgreSQL reads two): the only
    # permitted use of ';' is a single trailing terminator.
    if ";" in sql.strip().rstrip(";"):
        _reject("statement separators are not allowed", sql)
    stmt = statements[0]
    if not isinstance(stmt, (exp.Select, exp.Union)):
        _reject(f"only SELECT statements are allowed (found {type(stmt).__name__})", sql)

    for node in stmt.walk():
        if isinstance(node, _FORBIDDEN_NODES):
            _reject(f"{type(node).__name__} is not allowed (read-only SELECT only)", sql)
    for select in stmt.find_all(exp.Select):
        if select.args.get("into") is not None:
            _reject("SELECT INTO is not allowed", sql)
        if select.args.get("locks"):
            _reject("locking clauses (FOR UPDATE / FOR SHARE) are not allowed", sql)

    for with_ in stmt.find_all(exp.With):
        if with_.args.get("recursive"):
            _reject("recursive CTEs are not allowed", sql)

    cte_names = {c.alias_or_name.lower() for c in stmt.find_all(exp.CTE)}
    tables: list[str] = []
    for table in stmt.find_all(exp.Table):
        if not table.name or not isinstance(table.this, exp.Identifier):
            _reject("table-valued functions are not allowed", sql)
        if table.args.get("catalog"):
            _reject("catalog-qualified table names are not allowed", sql)
        schema = (table.db or "").lower()
        name = table.name.lower()
        if not schema and name in cte_names:
            continue
        qualified = f"{schema}.{name}" if schema else name
        if qualified not in allowed_tables:
            _reject(f"table {qualified or name!r} is not on the allow-list", sql)
        tables.append(qualified)

    functions: list[str] = []
    for node in stmt.find_all(exp.Func):
        name = _function_name(node)
        if not name:
            continue
        if any(p.fullmatch(name) for p in DENIED_FUNCTION_PATTERNS):
            _reject(f"function {name} is not allowed", sql)
        functions.append(name)

    limit = stmt.args.get("limit")
    if limit is None:
        _reject("a LIMIT is required", sql)
    limit_value = limit.expression if isinstance(limit, exp.Limit) else None
    if not isinstance(limit_value, exp.Literal) or limit_value.is_string or not limit_value.name.isdigit():
        _reject("the LIMIT must be an integer literal", sql)
    if int(limit_value.name) > max_rows:
        _reject(f"LIMIT {limit_value.name} exceeds the maximum of {max_rows} rows", sql)
    return GuardedSql(sql=sql, tables=tuple(sorted(set(tables))), functions=tuple(sorted(set(functions))),
                      limit=int(limit_value.name))
