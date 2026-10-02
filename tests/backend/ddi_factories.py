"""Builders for pure-engine tests (no database)."""

from __future__ import annotations

import random
from dataclasses import replace
from datetime import date, timedelta

from app.core.params import load_ddi_params, load_nbe_params
from app.domain.facts import DqIssue, EvidenceFacts, EvidenceItem, ExperimentFact, InsightFact, derive_item_dq_status

AS_OF = date(2026, 10, 1)
METRIC = "metric-success"
METRIC_DS = "ds-success"
PARAMS = load_ddi_params()
NBE = load_nbe_params(ddi_params=PARAMS)


def item(id: str, *, type: str = "behavioral", stance: str = "supports", grade: str = "A", tier: int = 1,
         end: date = AS_OF, source: str | None = None, ds: str | None = None, **kw) -> EvidenceItem:
    return EvidenceItem(id=id, evidence_type=type, stance=stance, strength_grade=grade, source_id=source or f"src-{id}",
                        reliability_tier=tier, observed_end=end, data_source_id=ds, **kw)


def facts(items, *, decision_type: str = "product_feature_investment", experiments=(), insights=(), dq=(),
          hetero: bool | None = None, metric_ds: str | None = METRIC_DS) -> EvidenceFacts:
    dq = tuple(dq)
    items = tuple(replace(i, dq_status=derive_item_dq_status(i.data_source_id, dq)) for i in items)
    return EvidenceFacts(decision_id="dec-1", decision_type=decision_type, success_metric_id=METRIC,
                         success_metric_data_source_id=metric_ds, items=items, experiments=tuple(experiments),
                         insights=tuple(insights), dq_issues=dq, heterogeneity_flag=hetero)


def strategy_facts(stance: str = "supports", **kw) -> EvidenceFacts:
    """Strong, diverse evidence for a decision type where D4 and D6 are not applicable (K = 5)."""
    items = [
        item("e1", type="market", stance=stance, source="s1", n_sample=500, effect_size=0.5, ci_low=0.45, ci_high=0.55, metric_id=METRIC),
        item("e2", type="customer", stance=stance, source="s2", n_sample=300, insight_id="ins-1"),
        item("e3", type="financial", stance=stance, source="s3", n_sample=300, effect_size=1.0, ci_low=0.9, ci_high=1.1),
    ]
    return facts(items, decision_type="strategy_or_market_entry", insights=[InsightFact("ins-1", 200)], **kw)


def good_experiment(id: str = "x1", metric: str = METRIC) -> ExperimentFact:
    return ExperimentFact(id=id, design="rct", primary_metric_id=metric, mde=0.02, result_n=4000, effect_size=0.03,
                          ci_low=0.01, ci_high=0.05, srm_flag=False)


def random_facts(rng: random.Random, *, decision_type: str | None = None) -> EvidenceFacts:
    """A random but valid fact set (>= 3 items, >= 2 types, linked to the success metric)."""
    dtype = decision_type or rng.choice(["product_feature_investment", "pricing_change", "process_or_ux_change",
                                         "strategy_or_market_entry", "policy_or_operations"])
    types = ["behavioral", "customer", "experiment", "financial", "market", "anecdotal"]
    n = rng.randint(3, 9)
    items, experiments, insights = [], [], []
    for k in range(n):
        t = rng.choice(types)
        kw = dict(
            type=t, stance=rng.choice(["supports", "supports", "contradicts", "neutral"]), grade=rng.choice("ABCD"),
            tier=rng.randint(1, 4), end=AS_OF - timedelta(days=rng.randint(0, 700)), source=f"src-{rng.randint(1, 4)}",
            ds=rng.choice([None, "ds-a", "ds-b"]), n_sample=rng.choice([None, 20, 150, 2000]),
            effect_size=rng.choice([None, 0.0, 0.01, 0.05, 0.4]),
        )
        if rng.random() < 0.6:
            lo = rng.uniform(-0.1, 0.1)
            kw.update(ci_low=lo, ci_high=lo + rng.uniform(0.0, 0.2))
        if t == "behavioral" and rng.random() < 0.7:
            kw["metric_id"] = METRIC
        if t == "experiment":
            kw["experiment_id"] = f"x{k}"
            experiments.append(ExperimentFact(
                f"x{k}", rng.choice(["rct", "holdout", "pre_post", "other"]), METRIC if rng.random() < 0.5 else None,
                rng.choice([None, 0.02]), 1000, 0.02, -0.01, 0.05, None, rng.choice([None, True, False])))
        if t == "customer":
            kw["insight_id"] = f"ins{k}"
            insights.append(InsightFact(f"ins{k}", rng.choice([5, 60, 200])))
        items.append(item(f"i{k:02d}", **kw))
    items[0] = replace(items[0], metric_id=METRIC)       # guarantee the success-metric link
    dq = []
    if rng.random() < 0.5:
        dq.append(DqIssue("q1", "ds-a", rng.choice(["warn", "critical"]), rng.choice(["open", "accepted", "resolved"])))
    return facts(items, decision_type=dtype, experiments=experiments, insights=insights, dq=dq,
                 hetero=rng.choice([None, False, True]), metric_ds=None)
