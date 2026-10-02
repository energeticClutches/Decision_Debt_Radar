"""EvidenceFacts: the single immutable input contract of the deterministic engines (R4).

Flow: Database -> repository -> EvidenceFacts -> DDI engine -> DDI result.
Everything here is plain data (str ids, float numbers, dates). Repositories convert Decimal to float
and UUID to str before constructing these objects. No behaviour that touches a database lives here.
"""

from __future__ import annotations

from collections.abc import Iterable
from dataclasses import dataclass, field
from datetime import date

EVIDENCE_TYPES = ("behavioral", "experiment", "customer", "financial", "market", "anecdotal")
STANCES = ("supports", "contradicts", "neutral")
DQ_STATUS_ORDER = {"pass": 0, "warn": 1, "critical": 2}


@dataclass(frozen=True)
class EvidenceItem:
    id: str
    evidence_type: str
    stance: str
    strength_grade: str
    source_id: str                 # evidence_sources.id (used for source concentration)
    reliability_tier: int          # 1..4, from the evidence source
    observed_end: date
    data_source_id: str | None = None
    dq_status: str = "pass"        # pass | warn | critical (derived by derive_item_dq_status)
    n_sample: int | None = None
    effect_size: float | None = None
    ci_low: float | None = None
    ci_high: float | None = None
    metric_id: str | None = None
    experiment_id: str | None = None
    insight_id: str | None = None


@dataclass(frozen=True)
class ExperimentFact:
    id: str
    design: str                    # rct | holdout | pre_post | other
    primary_metric_id: str | None = None
    mde: float | None = None
    # Result row of the non-control variant (largest n if several). None when no result is stored.
    result_n: int | None = None
    effect_size: float | None = None
    ci_low: float | None = None
    ci_high: float | None = None
    p_value: float | None = None
    srm_flag: bool | None = None   # True = sample-ratio mismatch detected. None = SRM check not stored
    achieved_power: float | None = None   # not stored in the schema on Day 3, so normally None


@dataclass(frozen=True)
class InsightFact:
    id: str
    quote_count: int
    segment: str | None = None


@dataclass(frozen=True)
class DqIssue:
    id: str
    data_source_id: str
    severity: str                  # pass | warn | critical
    status: str                    # open | resolved | accepted
    affects_metric_id: str | None = None
    check_type: str = ""
    finding: str = ""


@dataclass(frozen=True)
class EvidenceFacts:
    decision_id: str
    decision_type: str
    success_metric_id: str
    success_metric_data_source_id: str | None
    items: tuple[EvidenceItem, ...] = ()
    experiments: tuple[ExperimentFact, ...] = ()
    insights: tuple[InsightFact, ...] = ()
    dq_issues: tuple[DqIssue, ...] = ()
    # Heterogeneity is produced by the Day-4 analytics. None = unknown (treated as False, flagged).
    heterogeneity_flag: bool | None = None
    data_source_names: tuple[tuple[str, str], ...] = field(default_factory=tuple)  # (data_source_id, name)

    def experiment(self, experiment_id: str | None) -> ExperimentFact | None:
        if experiment_id is None:
            return None
        for e in self.experiments:
            if e.id == experiment_id:
                return e
        return None

    def data_source_name(self, data_source_id: str) -> str:
        for ds_id, name in self.data_source_names:
            if ds_id == data_source_id:
                return name
        return data_source_id


def derive_item_dq_status(data_source_id: str | None, dq_issues: Iterable[DqIssue]) -> str:
    """Worst severity among OPEN and ACCEPTED checks on the item's data source (resolved ones are ignored).

    An accepted limitation does not block scoring (R5) but the underlying data issue still exists, so it
    keeps lowering the item's dq_factor. This is the conservative choice and is shown in the breakdown.
    """
    worst = "pass"
    if data_source_id is None:
        return worst
    for issue in dq_issues:
        if issue.data_source_id != data_source_id or issue.status == "resolved":
            continue
        if DQ_STATUS_ORDER.get(issue.severity, 0) > DQ_STATUS_ORDER[worst]:
            worst = issue.severity
    return worst
