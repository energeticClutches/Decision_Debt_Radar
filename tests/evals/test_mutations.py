"""The seeded-flaw suite for the code layers (docs/day-7-implementation-brief.md section 2).

Syntheses are built from the REAL input payloads of the four scenarios (demo path, customer evidence approved). The assertions state what the
code layers must do; the numbers go to analytics/eval/mutation_results.json for the evaluation report. This measures validators and the
deterministic critic checks only. Reviewer recall and false flags are NOT EVIDENCED (no live model).
"""

from __future__ import annotations

import mutations as mt
import pytest
from day5_support import Scenario

_STATE: dict = {}


@pytest.fixture()
def suite(session, seed):
    scenarios = {name: Scenario(session, seed, name).run() for name in mt.SCENARIOS}
    payloads = {name: sc.evidence_input()[0] for name, sc in scenarios.items()}
    design_rank = scenarios["ai_coach"].ctx.ddi_params.design_rank
    results = mt.run_suite(payloads, design_rank)
    _STATE["results"] = results
    mt.write_results(results)
    return results


def test_the_mutation_file_is_well_formed():
    muts = mt.load_mutations()
    assert 20 <= len(muts) <= 30 and len({m["id"] for m in muts}) == len(muts)
    for m in muts:
        assert m["op"] in mt.OPS and m["catcher"]["layer"] in ("validator", "critic") and m["scenarios"]
        assert set(m["scenarios"]) <= set(mt.SCENARIOS)


def test_every_listed_flaw_family_of_the_brief_is_seeded():
    flaws = {m["flaw"] for m in mt.load_mutations()}
    for needed in ("unsupported_claim", "unknown_evidence_id", "foreign_decision_id", "valid_but_irrelevant_citation_type",
                   "mixed_stance_citation", "invented_ddi", "invented_percentage", "invented_effect_size", "invented_p_value",
                   "invented_confidence_interval", "invented_sample_size", "wrong_sign", "causal_claim_from_observational_evidence",
                   "recommendation_management_should", "sufficient_text_while_gated", "omitted_contradiction",
                   "ignored_critical_dq_issue", "high_confidence_on_grade_c_or_d"):
        assert needed in flaws, needed


def test_clean_controls_are_not_flagged_by_the_code_layers(suite):
    """False-flag rate of the code layers on valid syntheses of the four scenarios."""
    assert len(suite["controls"]) == 4
    flagged = [c for c in suite["controls"] if c["flagged"]]
    assert flagged == [], flagged


def test_every_seeded_flaw_is_caught_by_the_layer_that_must_catch_it(suite):
    missed = [i for i in suite["instances"] if i["applicable"] and not i["caught"] and not i.get("known_miss")]
    assert missed == [], [(i["id"], i["scenario"], i["validator_rules"], i["critic_categories"]) for i in missed]
    s = suite["summary"]
    assert s["instances"] >= 40 and s["flaw_types"] >= 20


def test_citation_validity_after_filtering_is_one_hundred_percent(suite):
    """PRD section 19: citation validity before filtering is reported; after filtering it must be 100% (every surviving claim cites existing active evidence)."""
    s = suite["summary"]
    assert s["citation_valid_after_filter"] == s["claims_surviving"]
    assert s["citation_valid_before_filter"] < s["claims_total"]          # the seeded flaws do contain invalid citations
