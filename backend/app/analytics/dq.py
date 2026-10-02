"""Data-quality checks (docs/day-4-implementation-brief.md section 5, D4-01 to D4-05, D4-23).

Per decision, over the views in its success metric's lineage and the views its planned analyses read:
  volume / tracking gap   per lineage event x platform: the per-signup daily rate in the recent window vs the baseline
  sequence                share of users with step k but without step k-1 (configured funnels)
  completeness            null rate of the required columns of the views
  duplicates              rows duplicated over each configured key (event_id, and user + event + timestamp for events)
  referential             rows whose user is not in the users view

Severity follows the thresholds (analytics_params_v0.1), then the impact rule: a finding at the critical threshold is
critical only if its target is in the success metric's lineage, otherwise it is capped at warn. check_key is
"{data_source_id}|{check_type}|{target}". The functions here compute findings; storing and reconciling them is
app.analytics.dq_store.

Window anchoring (the brief does not fix it, so this is documented in docs/day-4-implementation-notes.md): rates are
per signup, so the window ends on the last day on which the source has signups at or before the as-of date. The
baseline is the oldest baseline_days days of the window and the recent window its newest recent_days days.
"""

from __future__ import annotations

from collections import defaultdict
from collections.abc import Mapping
from dataclasses import dataclass, field
from datetime import UTC, date, datetime, timedelta
from typing import Any

from app.analytics import queries as Q
from app.analytics.config import AnalyticsParams, TenantConfig
from app.analytics.executor import ReadOnlyExecutor

SEVERITY_ORDER = {"pass": 0, "warn": 1, "critical": 2}


def utc_midnight(d: date) -> datetime:
    return datetime(d.year, d.month, d.day, tzinfo=UTC)


# ---------------------------------------------------------------- pure helpers
def severity_from_size(size: float | None, warn: float, critical: float) -> str:
    """pass when there is nothing to report (size None or <= 0); otherwise critical / warn by threshold (>=)."""
    if size is None or size <= 0:
        return "pass"
    if size >= critical:
        return "critical"
    if size >= warn:
        return "warn"
    return "pass"


def apply_impact_rule(severity: str, in_lineage: bool, rule: Mapping) -> str:
    """Impact over size: critical only when the target is in the success metric's lineage, else capped (default warn)."""
    if severity == "critical" and rule.get("critical_requires_lineage", True) and not in_lineage:
        return rule.get("non_lineage_cap", "warn")
    return severity


@dataclass(frozen=True)
class DqWindows:
    anchor: date                   # last day with signups at or before the as-of date
    window_start: datetime
    window_end: datetime           # exclusive
    baseline_start: datetime
    baseline_end: datetime         # exclusive
    recent_start: datetime
    recent_end: datetime           # exclusive
    as_of_ts: datetime

    def as_dict(self) -> dict:
        return {"anchor": self.anchor.isoformat(), "window": [self.window_start.date().isoformat(), self.window_end.date().isoformat()],
                "baseline": [self.baseline_start.date().isoformat(), self.baseline_end.date().isoformat()],
                "recent": [self.recent_start.date().isoformat(), self.recent_end.date().isoformat()],
                "as_of": self.as_of_ts.date().isoformat()}


def compute_windows(anchor: date, as_of: date, params: AnalyticsParams) -> DqWindows:
    dq = params.dq
    end = utc_midnight(anchor + timedelta(days=1))
    start = end - timedelta(days=dq["window_days"])
    return DqWindows(anchor=anchor, window_start=start, window_end=end, baseline_start=start,
                     baseline_end=start + timedelta(days=dq["baseline_days"]), recent_start=end - timedelta(days=dq["recent_days"]),
                     recent_end=end, as_of_ts=utc_midnight(as_of))


@dataclass(frozen=True)
class DqPlan:
    """What a decision's DQ run covers."""
    metric_name: str | None
    events: tuple[str, ...] = ()
    defining_events: frozenset[str] = frozenset()
    funnel_pairs: tuple[tuple[str, str], ...] = ()     # (step, previous step)
    views: tuple[str, ...] = ()
    lineage_views: frozenset[str] = frozenset()


def plan_for(tenant: TenantConfig, *, metric_name: str, scenario_key: str | None, linked_experiments: bool) -> DqPlan:
    """The events, funnels and views a decision's analyses read. Empty when the success metric has no analytics config."""
    metric = tenant.metric(metric_name)
    if metric is None:
        return DqPlan(metric_name=None)
    spec = tenant.decision_analyses(scenario_key)
    events: list[str] = list(metric.get("defining_events", []))
    outcome = metric["outcome"]
    if outcome["type"] in ("event_after_days", "event_within_days"):
        events.append(outcome["event"])
    views: list[str] = [metric["source_view"], *metric.get("lineage_views", [])]
    pairs: list[tuple[str, str]] = []
    if spec.get("funnel"):
        steps = tenant.funnel(spec["funnel"])
        events.extend(steps)
        pairs = [(steps[i], steps[i - 1]) for i in range(1, len(steps))]
        views.extend(["fc_.v_events", "fc_.v_users"])
    comp = spec.get("comparison")
    if comp:
        if comp["type"] == "event_users":
            events.append(comp["treatment_event"])
            views.append("fc_.v_events")
            if comp.get("exclude_experiment_participants"):
                views.append("fc_.v_experiment_assignments")
        views.append("fc_.v_users")
    if linked_experiments:
        views.extend(["fc_.v_experiment_assignments", "fc_.v_experiment_outcomes", "fc_.v_users"])
    ordered_events = tuple(dict.fromkeys(events))
    ordered_views = tuple(dict.fromkeys(views))
    lineage = frozenset([metric["source_view"], *metric.get("lineage_views", [])])
    return DqPlan(metric_name=metric_name, events=ordered_events, defining_events=frozenset(metric.get("defining_events", [])),
                  funnel_pairs=tuple(pairs), views=ordered_views, lineage_views=lineage)


@dataclass(frozen=True)
class DqFinding:
    check_type: str                # volume | sequence | completeness | duplicates | referential
    data_source_ref: str           # evidence_sources.ref of the data source of the view
    target: str
    view: str
    in_lineage: bool               # the target is in the success metric's lineage
    size: float | None             # the measured size the thresholds apply to
    threshold: float               # the threshold that decided the raw severity
    raw_severity: str              # by size alone
    severity: str                  # after the impact rule
    finding: str
    snapshot: str

    @property
    def observed_value(self) -> float | None:
        return self.size


def _finding(*, check_type: str, view: str, ref: str, target: str, in_lineage: bool, size: float | None, warn: float,
             critical: float, params: AnalyticsParams, text: str, snapshot: str) -> DqFinding:
    raw = severity_from_size(size, warn, critical)
    final = apply_impact_rule(raw, in_lineage, params["severity_rule"])
    threshold = critical if raw == "critical" else warn
    if raw != final:
        text += (f" The size reaches the critical threshold ({critical}) but the target is not in the success metric's lineage, "
                 f"so the severity is capped at {final}.")
    return DqFinding(check_type=check_type, data_source_ref=ref, target=target, view=view, in_lineage=in_lineage, size=size,
                     threshold=threshold, raw_severity=raw, severity=final, finding=text, snapshot=snapshot)


# ---------------------------------------------------------------- volume
def evaluate_volume(*, event: str, platform: str, daily_events: Mapping[date, int], daily_signups: Mapping[date, int],
                    windows: DqWindows, params: AnalyticsParams) -> tuple[float | None, str, dict]:
    """Returns (drop, explanation, details). drop = 1 - recent per-signup rate / baseline per-signup rate. None when the rate
    cannot be assessed (no baseline) or when a drop is not sustained for min_sustained_days."""
    dq = params.dq
    vol = dq["volume"]

    def window_sums(start: datetime, end: datetime) -> tuple[int, int]:
        days = [start.date() + timedelta(days=i) for i in range((end.date() - start.date()).days)]
        return sum(daily_events.get(d, 0) for d in days), sum(daily_signups.get(d, 0) for d in days)

    b_events, b_signups = window_sums(windows.baseline_start, windows.baseline_end)
    r_events, r_signups = window_sums(windows.recent_start, windows.recent_end)
    details = {"baseline_events": b_events, "baseline_signups": b_signups, "recent_events": r_events, "recent_signups": r_signups}
    if b_signups == 0 or b_events == 0:
        return None, f"{event} on {platform}: no baseline (no {'signups' if b_signups == 0 else 'events'} in the baseline window).", details
    if r_signups == 0:
        return None, f"{event} on {platform}: no signups in the recent window, so the per-signup rate cannot be assessed.", details
    b_rate, r_rate = b_events / b_signups, r_events / r_signups
    drop = 1 - r_rate / b_rate
    warn_level = (1 - vol["warn_pct_drop"]) * b_rate
    recent_days = [windows.recent_start.date() + timedelta(days=i) for i in range((windows.recent_end - windows.recent_start).days)]
    below = sum(1 for d in recent_days if daily_signups.get(d, 0) > 0 and daily_events.get(d, 0) / daily_signups[d] <= warn_level)
    details.update({"baseline_rate": b_rate, "recent_rate": r_rate, "recent_days_below_warn_level": below})
    needed = dq["min_sustained_days"]
    if drop >= vol["warn_pct_drop"] and below < needed:
        return None, (f"{event} on {platform}: the per-signup rate fell {drop:.0%} but on only {below} of {len(recent_days)} recent days "
                      f"(a sustained drop needs at least {needed}), so it is not reported as a defect."), details
    text = (f"{event} on {platform}: per-signup daily rate {'fell' if drop >= 0 else 'rose'} {abs(drop):.0%} "
            f"(baseline {b_rate:.4f}, recent {r_rate:.4f} events per signup per day; below the warn level on {below} of "
            f"{len(recent_days)} recent days).")
    return drop, text, details


# ---------------------------------------------------------------- the run
@dataclass
class DqRun:
    windows: DqWindows | None
    findings: list[DqFinding] = field(default_factory=list)
    notes: list[str] = field(default_factory=list)


def run_checks(executor: ReadOnlyExecutor, params: AnalyticsParams, tenant: TenantConfig, plan: DqPlan, as_of: date) -> DqRun:
    """Run every check of the plan through the read-only executor and return the findings (pass rows included)."""
    if plan.metric_name is None:
        return DqRun(windows=None, notes=["the success metric has no analytics configuration: no data-quality checks were run"])
    max_rows = params.max_rows
    as_of_ts = utc_midnight(as_of)
    anchor_rows = executor.run(Q.anchor_query(max_rows), {"as_of_ts": as_of_ts})
    anchor = anchor_rows[0]["last_signup_date"] if anchor_rows and anchor_rows[0]["last_signup_date"] else as_of - timedelta(days=1)
    windows = compute_windows(anchor, as_of, params)
    dq = params.dq
    run = DqRun(windows=windows)
    events_ref = tenant.data_source_ref("fc_.v_events")
    rule = params["severity_rule"]

    # ---- volume
    if plan.events:
        ev_rows = executor.run(Q.volume_events_query(max_rows), {"window_start": windows.window_start, "window_end": windows.window_end,
                                                                 "events": list(plan.events)})
        su_rows = executor.run(Q.signups_per_day_query(max_rows), {"window_start": windows.window_start, "window_end": windows.window_end})
        by_event: dict[tuple[str, str], dict[date, int]] = defaultdict(dict)
        signups: dict[str, dict[date, int]] = defaultdict(dict)
        platforms: set[str] = set()
        for r in ev_rows:
            by_event[(r["event_name"], r["platform"])][r["day"]] = int(r["n"])
            platforms.add(r["platform"])
        for r in su_rows:
            signups[r["platform"]][r["day"]] = int(r["n"])
            platforms.add(r["platform"])
        snapshot = f"fc_.v_events as of {as_of.isoformat()}, window {windows.window_start.date()}..{windows.window_end.date()} (exclusive)"
        for event in plan.events:
            for platform in sorted(platforms):
                drop, text, details = evaluate_volume(event=event, platform=platform, daily_events=by_event.get((event, platform), {}),
                                                      daily_signups=signups.get(platform, {}), windows=windows, params=params)
                run.findings.append(_finding(
                    check_type="volume", view="fc_.v_events", ref=events_ref, target=f"{event}@{platform}",
                    in_lineage=event in plan.defining_events, size=drop, warn=dq["volume"]["warn_pct_drop"],
                    critical=dq["volume"]["critical_pct_drop"], params=params, text=text,
                    snapshot=snapshot + f"; baseline_signups={details['baseline_signups']} recent_signups={details['recent_signups']}"))

    # ---- sequence
    for step, previous in plan.funnel_pairs:
        rows = executor.run(Q.sequence_query(max_rows), {"window_start": windows.window_start, "window_end": windows.window_end,
                                                         "step": step, "previous_step": previous, "pair": [step, previous]})
        lineage = step in plan.defining_events or previous in plan.defining_events
        for r in rows:
            users, violations = int(r["users"]), int(r["violations"])
            rate = violations / users if users else None
            run.findings.append(_finding(
                check_type="sequence", view="fc_.v_events", ref=events_ref, target=f"{step}>{previous}@{r['platform']}",
                in_lineage=lineage, size=rate, warn=dq["sequence"]["warn_rate"], critical=dq["sequence"]["critical_rate"],
                params=params,
                text=(f"{violations} of {users} signups on {r['platform']} have {step} without {previous} "
                      f"({(rate or 0):.2%} of signups in the window)."),
                snapshot=f"fc_.v_events/fc_.v_users cohort {windows.window_start.date()}..{windows.window_end.date()}, users={users}"))

    # ---- completeness, duplicates, referential
    for view in plan.views:
        spec = tenant.view(view)
        ref = tenant.data_source_ref(view)
        ts = spec.get("ts_column")
        in_lineage = view in plan.lineage_views
        win = {"window_start": windows.window_start, "as_of_ts": as_of_ts} if ts else {}
        scope = f"window {windows.window_start.date()}..{as_of.isoformat()}" if ts else "all rows"
        cols = list(spec.get("required_columns", []))
        if cols:
            (row,) = executor.run(Q.completeness_query(view, cols, ts, max_rows), win)
            n = int(row["n"])
            for c in cols:
                nulls = int(row[f"{c}_nulls"])
                rate = nulls / n if n else None
                run.findings.append(_finding(
                    check_type="completeness", view=view, ref=ref, target=f"{view}.{c}", in_lineage=in_lineage, size=rate,
                    warn=dq["completeness"]["warn_null_rate"], critical=dq["completeness"]["critical_null_rate"], params=params,
                    text=f"{view}.{c}: {nulls} null of {n} rows ({(rate or 0):.3%}).", snapshot=f"{view} {scope}, rows={n}"))
        for key in spec.get("key_columns", []):
            (row,) = executor.run(Q.duplicates_query(view, key, ts, max_rows), win)
            n, dup = int(row["n"]), int(row["duplicates"])
            rate = dup / n if n else None
            run.findings.append(_finding(
                check_type="duplicates", view=view, ref=ref, target=f"{view}({','.join(key)})", in_lineage=in_lineage, size=rate,
                warn=dq["duplicates"]["warn_rate"], critical=dq["duplicates"]["critical_rate"], params=params,
                text=f"{view}({','.join(key)}): {dup} duplicate rows of {n} ({(rate or 0):.3%}).", snapshot=f"{view} {scope}, rows={n}"))
        user_col = spec.get("user_column")
        if user_col and view != "fc_.v_users":
            (row,) = executor.run(Q.referential_query(view, user_col, ts, max_rows), win)
            n, orphans = int(row["n"]), int(row["orphans"])
            rate = orphans / n if n else None
            run.findings.append(_finding(
                check_type="referential", view=view, ref=ref, target=f"{view}.{user_col}", in_lineage=in_lineage, size=rate,
                warn=dq["referential"]["warn_rate"], critical=dq["referential"]["critical_rate"], params=params,
                text=f"{view}.{user_col}: {orphans} of {n} rows reference a user that is not in fc_.v_users ({(rate or 0):.3%}).",
                snapshot=f"{view} {scope}, rows={n}"))
    return run


def summarize(findings: list[DqFinding]) -> dict[str, Any]:
    counts = {"pass": 0, "warn": 0, "critical": 0}
    for f in findings:
        counts[f.severity] += 1
    return counts
