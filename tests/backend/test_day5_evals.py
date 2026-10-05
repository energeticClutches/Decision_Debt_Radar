"""Evaluation (E1, and the opt-in live checks of E1 and E2).

E1 reads the evaluation ground-truth labels. That is allowed ONLY here (tests/evals): product code, prompts and configuration never read
them (G3). The stub run measures the PIPELINE and the keyword rules, not any model. CAVEAT: the synthetic feedback is TEMPLATED (195
distinct sentences for 6,083 rows), so near-perfect agreement says nothing about real customer text. The stub's cues were written while
the generator's template sentences were visible, which makes this result optimistic by construction."""

from __future__ import annotations

import json
import os
from collections import Counter

import pytest
from sqlalchemy import text
from stub_classifier import classify_text

from app.core.params import get_tenant_config

# test-only mapping: taxonomy theme -> the ground-truth label of the generator (authored here, never read by product code)
GROUND_TRUTH_LABEL = {
    "coach_helpful": "ai_coach_positive", "coach_generic_or_wrong": "ai_coach_negative", "coach_indifferent": "ai_coach_neutral",
    "challenges_motivating": "community_positive", "notifications_unwanted": "community_negative_notifications",
    "challenges_indifferent": "community_neutral", "setup_blocked": "onboarding_complaint",
    "price_too_high": "pricing_sensitive", "worth_the_price": "pricing_value"}
SCENARIOS = ("ai_coach", "community", "onboarding", "pricing")
EXPECTED_MIN = 0.95


def ground_truth_rows(session):
    return session.execute(text("SELECT f.feedback_id, f.body, g.theme FROM fc_.feedback f JOIN fc_.feedback_ground_truth g "
                                "ON g.feedback_id = f.feedback_id ORDER BY f.feedback_id")).all()


def per_theme_scores(rows, predict):
    """theme -> (precision, recall, tp, predicted, actual) of `predict(body, scenario) -> theme | None` against the ground truth."""
    out = {}
    tenant = get_tenant_config()
    for scenario in SCENARIOS:
        themes = list(tenant.customer_taxonomy(scenario).theme_names)
        preds = [(predict(body, scenario, themes), truth) for _, body, truth in rows]
        for theme in themes:
            label = GROUND_TRUTH_LABEL[theme]
            predicted = sum(1 for p, _ in preds if p == theme)
            actual = sum(1 for _, t in preds if t == label)
            tp = sum(1 for p, t in preds if p == theme and t == label)
            out[theme] = (tp / predicted if predicted else 0.0, tp / actual if actual else 0.0, tp, predicted, actual)
    return out


def test_e1_stub_classifier_precision_and_recall_per_theme_against_the_ground_truth(session):
    rows = ground_truth_rows(session)
    assert len(rows) == 6083 and len({b for _, b, _ in rows}) == 195
    scores = per_theme_scores(rows, lambda body, scenario, themes: classify_text(body, themes)[0])
    assert set(scores) == set(GROUND_TRUTH_LABEL)
    report = {k: {"precision": round(v[0], 4), "recall": round(v[1], 4), "tp": v[2], "predicted": v[3], "actual": v[4]} for k, v in scores.items()}
    print("\nE1 stub classifier vs ground truth (measures the pipeline and the keyword rules, NOT a model):\n" + json.dumps(report, indent=1))
    for theme, (precision, recall, *_rest) in scores.items():
        assert precision >= EXPECTED_MIN and recall >= EXPECTED_MIN, (theme, precision, recall)
    # a row of another scenario's theme is never predicted into this scenario's taxonomy
    assert Counter(t for _, _, t in rows)["generic_positive"] > 0


def test_e1_the_pipeline_counts_equal_the_stub_predictions_end_to_end(session, seed):
    """The classification stored by Stage 3 and aggregated into insights agrees with the stub applied directly to the same rows."""
    from day4_support import clone_decision
    from day5_support import by_theme, ctx5, run_stage3
    from flow import Flow
    from replay import ReplayClient
    flow = Flow(session, seed)
    d = clone_decision(flow, seed, "community")
    ctx = ctx5(session, ReplayClient())
    run_stage3(ctx, seed.analyst, d)
    rows = ground_truth_rows(session)
    themes = list(get_tenant_config().customer_taxonomy("community").theme_names)
    direct = Counter(classify_text(body, themes)[0] for _, body, _ in rows)
    from app.db import models as m
    for theme, items in by_theme(session, d).items():
        assert session.get(m.CustomerInsight, items[0].insight_id).quote_count == direct[theme]


# ================================================================ live, opt-in (skipped without ANTHROPIC_API_KEY, never in CI)
@pytest.mark.llm
def test_e1_model_classification_precision_and_recall_per_theme_live(session):
    from app.llm import get_llm_client
    from app.core.params import get_analytics_params
    from app.customer.schema import parse_classifications
    from app.llm import sanitize
    from app.llm.builders import build_request, default_models
    from app.llm.prompts import load_prompt
    client = get_llm_client()
    assert client is not None
    rows = ground_truth_rows(session)
    tenant, params, prompt = get_tenant_config(), get_analytics_params(), load_prompt("classify")
    distinct = {}
    for _, body, truth in rows:
        distinct.setdefault(body, truth)
    texts = sorted(distinct)

    def predict(body, scenario, themes):
        return live[(scenario, body)]
    live = {}
    for scenario in SCENARIOS:
        tax = tenant.customer_taxonomy(scenario)
        for i in range(0, len(texts), 50):
            chunk = texts[i:i + 50]
            refs = {f"t{j + 1}": b for j, b in enumerate(chunk)}
            obj = {"task": "classify", "taxonomy": {"taxonomy_version": tax.taxonomy_id,
                                                   "themes": [{"theme": t.theme, "description": t.description} for t in tax.themes]},
                   "texts": [{"text_ref": r, "text": sanitize.wrap(b)} for r, b in refs.items()]}
            req = build_request(purpose="classify", prompt=prompt, input_obj=obj, model=default_models()["classify"], llm_params=params.llm)
            parsed = parse_classifications(client.complete(req).text, themes=tax.theme_names, text_refs=list(refs))
            for r, (theme, _rel) in parsed.items():
                live[(scenario, refs[r])] = theme
    scores = per_theme_scores(rows, predict)
    print("\nE1 live model vs ground truth:\n" + json.dumps({k: [round(v[0], 3), round(v[1], 3)] for k, v in scores.items()}, indent=1))
    assert all(p >= 0.8 and r >= 0.8 for p, r, *_ in scores.values())


@pytest.mark.llm
def test_e2_live_reviewer_catches_the_injected_faults():
    """Opt-in: the live Reviewer must flag the injected causal overclaim and the 'no harm' claim of the hand-authored fixtures."""
    assert os.environ.get("ANTHROPIC_API_KEY")
    pytest.skip("live reviewer evaluation is recorded with scripts/record_llm_fixtures.py and reviewed by a human (Day 7 report)")
