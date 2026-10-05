"""Catalogue of parameterised SQL templates (docs/day-4-implementation-brief.md section 9).

Every query that Day-4 analytics runs is built here from a fixed template. Values are bound parameters (`:name`),
never interpolated. The only text spliced into a template is an identifier (a column or an allow-listed view) that
comes from the validated tenant configuration and is checked against a strict identifier pattern, or a row limit
that is an integer constant. Every template goes through the SQL guard before it is executed, and there is no other
way to run SQL (the executor accepts only a QueryTemplate). There is no LLM-generated SQL.
"""

from __future__ import annotations

import re
from collections.abc import Mapping, Sequence
from dataclasses import dataclass

from app.analytics.sql_guard import ALLOWED_TABLES, DEFAULT_MAX_ROWS

_PARAM = re.compile(r"(?<![:\w]):([A-Za-z_]\w*)")
_IDENT = re.compile(r"^[a-z_][a-z0-9_]*$")


@dataclass(frozen=True)
class QueryTemplate:
    name: str
    sql: str
    params: tuple[str, ...]

    @staticmethod
    def build(name: str, sql: str) -> QueryTemplate:
        sql = " ".join(sql.split())
        return QueryTemplate(name=name, sql=sql, params=tuple(sorted(set(_PARAM.findall(sql)))))


def _ident(value: str) -> str:
    if not isinstance(value, str) or not _IDENT.match(value):
        raise ValueError(f"not a valid SQL identifier: {value!r}")
    return value


def _view(value: str) -> str:
    if value not in ALLOWED_TABLES or not value.startswith("fc_.v_"):
        raise ValueError(f"view {value!r} is not allow-listed")
    return value


def _limit(max_rows: int) -> str:
    return f"LIMIT {int(max_rows)}"


# ---------------------------------------------------------------- data quality
def anchor_query(max_rows: int = DEFAULT_MAX_ROWS) -> QueryTemplate:
    """The last day on which the source has signups at or before the as-of instant (the DQ window anchor)."""
    return QueryTemplate.build("dq.anchor", f"""
        SELECT (max(signup_ts) AT TIME ZONE 'UTC')::date AS last_signup_date, count(*) AS signups
        FROM fc_.v_users WHERE signup_ts < :as_of_ts {_limit(max_rows)}""")


def volume_events_query(max_rows: int = DEFAULT_MAX_ROWS) -> QueryTemplate:
    return QueryTemplate.build("dq.volume.events", f"""
        SELECT (e.event_ts AT TIME ZONE 'UTC')::date AS day, e.event_name AS event_name, e.platform AS platform,
               count(*) AS n
        FROM fc_.v_events e
        WHERE e.event_ts >= :window_start AND e.event_ts < :window_end AND e.event_name = ANY(CAST(:events AS text[]))
        GROUP BY 1, 2, 3 ORDER BY 1, 2, 3 {_limit(max_rows)}""")


def signups_per_day_query(max_rows: int = DEFAULT_MAX_ROWS) -> QueryTemplate:
    return QueryTemplate.build("dq.volume.signups", f"""
        SELECT (u.signup_ts AT TIME ZONE 'UTC')::date AS day, u.platform AS platform, count(*) AS n
        FROM fc_.v_users u WHERE u.signup_ts >= :window_start AND u.signup_ts < :window_end
        GROUP BY 1, 2 ORDER BY 1, 2 {_limit(max_rows)}""")


def sequence_query(max_rows: int = DEFAULT_MAX_ROWS) -> QueryTemplate:
    """Users of the cohort window that have step k but not step k-1, per platform."""
    return QueryTemplate.build("dq.sequence", f"""
        WITH cohort AS (
          SELECT user_id, platform FROM fc_.v_users WHERE signup_ts >= :window_start AND signup_ts < :window_end),
        steps AS (
          SELECT e.user_id AS user_id, bool_or(e.event_name = :step) AS has_step,
                 bool_or(e.event_name = :previous_step) AS has_previous
          FROM fc_.v_events e JOIN cohort c ON c.user_id = e.user_id
          WHERE e.event_name = ANY(CAST(:pair AS text[])) GROUP BY e.user_id)
        SELECT c.platform AS platform, count(*) AS users,
               count(*) FILTER (WHERE COALESCE(s.has_step, false) AND NOT COALESCE(s.has_previous, false)) AS violations
        FROM cohort c LEFT JOIN steps s ON s.user_id = c.user_id
        GROUP BY c.platform ORDER BY c.platform {_limit(max_rows)}""")


def _window_clause(alias: str, ts_column: str | None) -> tuple[str, bool]:
    if ts_column is None:
        return "", False
    col = _ident(ts_column)
    return f" WHERE {alias}.{col} >= :window_start AND {alias}.{col} < :as_of_ts", True


def completeness_query(view: str, columns: Sequence[str], ts_column: str | None,
                       max_rows: int = DEFAULT_MAX_ROWS) -> QueryTemplate:
    """Row count and null count of each required column of a view, over the DQ window when the view has a timestamp."""
    view = _view(view)
    cols = [_ident(c) for c in columns]
    where, _ = _window_clause("t", ts_column)
    nulls = ", ".join(f"count(*) FILTER (WHERE t.{c} IS NULL) AS {c}_nulls" for c in cols)
    return QueryTemplate.build(f"dq.completeness.{view}", f"SELECT count(*) AS n, {nulls} FROM {view} t{where} {_limit(max_rows)}")


def duplicates_query(view: str, key_columns: Sequence[str], ts_column: str | None,
                     max_rows: int = DEFAULT_MAX_ROWS) -> QueryTemplate:
    view = _view(view)
    cols = [_ident(c) for c in key_columns]
    where, _ = _window_clause("t", ts_column)
    key = f"t.{cols[0]}" if len(cols) == 1 else "(" + ", ".join(f"t.{c}" for c in cols) + ")"
    return QueryTemplate.build(f"dq.duplicates.{view}.{'.'.join(cols)}", f"""
        SELECT count(*) AS n, count(*) - count(DISTINCT {key}) AS duplicates FROM {view} t{where} {_limit(max_rows)}""")


def referential_query(view: str, user_column: str, ts_column: str | None, max_rows: int = DEFAULT_MAX_ROWS) -> QueryTemplate:
    view = _view(view)
    col = _ident(user_column)
    where, _ = _window_clause("t", ts_column)
    return QueryTemplate.build(f"dq.referential.{view}", f"""
        SELECT count(*) AS n, count(*) FILTER (WHERE u.user_id IS NULL) AS orphans
        FROM {view} t LEFT JOIN fc_.v_users u ON u.user_id = t.{col}{where} {_limit(max_rows)}""")


# ---------------------------------------------------------------- metric outcomes (comparison, trend)
def outcome_select(outcome: Mapping, segment_column: str | None, population_column: str | None = None) -> tuple[str, tuple[str, ...]]:
    """SELECT returning one row per unit: user_id, signup_ts, segment, outcome (boolean). Returns (sql, param names)."""
    seg = f"u.{_ident(segment_column)}" if segment_column else "CAST(NULL AS text)"
    pop = f" AND u.{_ident(population_column)} = :population_value" if population_column else ""
    kind = outcome["type"]
    if kind == "event_after_days":
        sql = (f"SELECT u.user_id AS user_id, u.signup_ts AS signup_ts, {seg} AS segment, "
               "EXISTS (SELECT 1 FROM fc_.v_events e WHERE e.user_id = u.user_id AND e.event_name = :outcome_event "
               "AND e.event_ts >= u.signup_ts + (:outcome_days * INTERVAL '1 day')) AS outcome "
               f"FROM fc_.v_users u WHERE u.signup_ts < :cohort_end{pop}")
        return sql, ("outcome_event", "outcome_days", "cohort_end")
    if kind == "event_within_days":
        sql = (f"SELECT u.user_id AS user_id, u.signup_ts AS signup_ts, {seg} AS segment, "
               "EXISTS (SELECT 1 FROM fc_.v_events e WHERE e.user_id = u.user_id AND e.event_name = :outcome_event "
               "AND e.event_ts >= u.signup_ts AND e.event_ts < u.signup_ts + (:outcome_days * INTERVAL '1 day')) AS outcome "
               f"FROM fc_.v_users u WHERE u.signup_ts < :cohort_end{pop}")
        return sql, ("outcome_event", "outcome_days", "cohort_end")
    if kind == "subscription_status":
        sql = (f"SELECT u.user_id AS user_id, u.signup_ts AS signup_ts, {seg} AS segment, (s.status = :outcome_status) AS outcome "
               "FROM fc_.v_subscriptions s JOIN fc_.v_users u ON u.user_id = s.user_id "
               f"WHERE s.plan = :outcome_plan AND u.signup_ts < :cohort_end{pop}")
        return sql, ("outcome_plan", "outcome_status", "cohort_end")
    raise ValueError(f"unknown outcome type {kind!r}")


def outcome_params(outcome: Mapping) -> dict:
    kind = outcome["type"]
    if kind in ("event_after_days", "event_within_days"):
        return {"outcome_event": outcome["event"], "outcome_days": int(outcome["days"])}
    return {"outcome_plan": outcome["plan"], "outcome_status": outcome["status"]}


def comparison_query(metric_outcome: Mapping, segment_column: str, comparison: Mapping,
                     max_rows: int = DEFAULT_MAX_ROWS) -> QueryTemplate:
    """Treatment vs comparison counts by segment: arm, segment, n, k (outcome count), first and last signup."""
    pop = comparison.get("population") or {}
    outcomes, _ = outcome_select(metric_outcome, segment_column, pop.get("column"))
    kind = comparison["type"]
    if kind == "event_users":
        exclusion = ""
        if comparison.get("exclude_experiment_participants"):
            exclusion = (" AND user_id NOT IN (SELECT user_id FROM fc_.v_experiment_assignments "
                         "WHERE experiment_key = ANY(CAST(:excluded_experiments AS text[])))")
        treat = (f", treat AS (SELECT DISTINCT user_id FROM fc_.v_events WHERE event_name = :treatment_event{exclusion})")
        arm = "CASE WHEN o.user_id IN (SELECT user_id FROM treat) THEN 'treatment' ELSE 'comparison' END"
    elif kind == "cohort_split":
        treat = ""
        arm = "CASE WHEN o.signup_ts >= :split_ts THEN 'treatment' ELSE 'comparison' END"
    else:
        raise ValueError(f"unknown comparison type {kind!r}")
    return QueryTemplate.build(f"comparison.{kind}", f"""
        WITH outcomes AS ({outcomes}){treat},
        arms AS (SELECT o.signup_ts AS signup_ts, o.segment AS segment, o.outcome AS outcome, {arm} AS arm FROM outcomes o)
        SELECT arm, segment, count(*) AS n, count(*) FILTER (WHERE outcome) AS k,
               min(signup_ts) AS first_signup, max(signup_ts) AS last_signup
        FROM arms GROUP BY arm, segment ORDER BY arm, segment {_limit(max_rows)}""")


def trend_query(metric_outcome: Mapping, max_rows: int = DEFAULT_MAX_ROWS) -> QueryTemplate:
    outcomes, _ = outcome_select(metric_outcome, None)
    return QueryTemplate.build("trend.weekly", f"""
        WITH outcomes AS ({outcomes})
        SELECT date_trunc('week', o.signup_ts AT TIME ZONE 'UTC')::date AS week_start, count(*) AS n,
               count(*) FILTER (WHERE o.outcome) AS k, (max(o.signup_ts) AT TIME ZONE 'UTC')::date AS last_signup_date
        FROM outcomes o WHERE o.signup_ts >= :trend_start GROUP BY 1 ORDER BY 1 {_limit(max_rows)}""")


# ---------------------------------------------------------------- funnel
def funnel_cohort_query(max_rows: int = DEFAULT_MAX_ROWS) -> QueryTemplate:
    return QueryTemplate.build("funnel.cohort", f"""
        SELECT u.platform AS platform, count(*) AS users FROM fc_.v_users u
        WHERE u.signup_ts >= :window_start AND u.signup_ts < :window_end GROUP BY 1 ORDER BY 1 {_limit(max_rows)}""")


def funnel_steps_query(max_rows: int = DEFAULT_MAX_ROWS) -> QueryTemplate:
    return QueryTemplate.build("funnel.steps", f"""
        WITH cohort AS (SELECT user_id, platform FROM fc_.v_users WHERE signup_ts >= :window_start AND signup_ts < :window_end),
        reached AS (SELECT DISTINCT e.user_id AS user_id, e.event_name AS event_name
                    FROM fc_.v_events e JOIN cohort c ON c.user_id = e.user_id
                    WHERE e.event_name = ANY(CAST(:steps AS text[])))
        SELECT c.platform AS platform, r.event_name AS event_name, count(*) AS users
        FROM reached r JOIN cohort c ON c.user_id = r.user_id GROUP BY 1, 2 ORDER BY 1, 2 {_limit(max_rows)}""")


# ---------------------------------------------------------------- experiments
def experiment_assignments_query(max_rows: int = DEFAULT_MAX_ROWS) -> QueryTemplate:
    return QueryTemplate.build("experiment.assignments", f"""
        SELECT variant, count(*) AS n FROM fc_.v_experiment_assignments
        WHERE experiment_key = :experiment_key GROUP BY variant ORDER BY variant {_limit(max_rows)}""")


def experiment_outcomes_query(max_rows: int = DEFAULT_MAX_ROWS) -> QueryTemplate:
    return QueryTemplate.build("experiment.outcomes", f"""
        SELECT a.variant AS variant, count(*) AS n, avg(o.value) AS mean, stddev_samp(o.value) AS sd,
               count(*) FILTER (WHERE o.value NOT IN (0, 1)) AS non_binary
        FROM fc_.v_experiment_assignments a
        JOIN fc_.v_experiment_outcomes o ON o.experiment_key = a.experiment_key AND o.user_id = a.user_id
        WHERE a.experiment_key = :experiment_key AND o.metric_name = :outcome_key
        GROUP BY a.variant ORDER BY a.variant {_limit(max_rows)}""")


# ---------------------------------------------------------------- customer feedback (Day 5, Stage 3)
def feedback_candidates_query(spec: Mapping, segment_column: str | None, max_rows: int = DEFAULT_MAX_ROWS) -> QueryTemplate:
    """The feedback rows of the analysis window (created before :window_end, the instant after the as-of day), one row per
    feedback item, ordered by id. Read ONLY through the allow-listed feedback view; the evaluation ground-truth table is neither
    allow-listed nor ever named here. `segment` is the configured segment column of the users view (informational counts only)."""
    view = _view(spec["view"])
    fid, text_col, ts, source, user = (_ident(spec[k]) for k in ("id_column", "text_column", "ts_column", "source_column", "user_column"))
    seg = f"u.{_ident(segment_column)}" if segment_column else "CAST(NULL AS text)"
    join = f" LEFT JOIN fc_.v_users u ON u.user_id = f.{user}" if segment_column else ""
    return QueryTemplate.build("customer.feedback_candidates", f"""
        SELECT f.{fid} AS feedback_id, f.{text_col} AS body, f.{ts} AS created_at, f.{source} AS source, {seg} AS segment
        FROM {view} f{join} WHERE f.{ts} < :window_end ORDER BY f.{fid} {_limit(max_rows)}""")
