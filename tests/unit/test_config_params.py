"""Structural checks on the versioned DDI/NBE parameter files (Day 1).

These do not test scoring (the engine arrives on Day 3). They guard the config
structure against the approved specs so later code can rely on it.
"""

from pathlib import Path

import pytest
import yaml

CONFIG = Path(__file__).resolve().parents[2] / "backend" / "config"
DDI_FILE = CONFIG / "ddi" / "ddi_params_v0.1.yaml"
NBE_FILE = CONFIG / "nbe" / "nbe_params_v0.1.yaml"


@pytest.fixture(scope="module")
def ddi():
    return yaml.safe_load(DDI_FILE.read_text(encoding="utf-8"))


@pytest.fixture(scope="module")
def nbe():
    return yaml.safe_load(NBE_FILE.read_text(encoding="utf-8"))


def test_version_matches_filename(ddi, nbe):
    assert ddi["version"] == DDI_FILE.stem
    assert nbe["version"] == NBE_FILE.stem
    assert nbe["ddi_params_version"] == ddi["version"]


def test_ddi_factor_tables_are_complete_and_in_range(ddi):
    assert set(ddi["tier_factor"]) == {1, 2, 3, 4}
    assert set(ddi["grade_factor"]) == {"A", "B", "C", "D"}
    assert set(ddi["dq_factor"]) == {"pass", "warn", "critical"}
    for table in ("tier_factor", "grade_factor", "dq_factor", "design_rank"):
        assert all(0.0 <= v <= 1.0 for v in ddi[table].values()), table


def test_half_lives_cover_all_evidence_types(ddi):
    expected = {"behavioral", "experiment", "customer", "financial", "market", "anecdotal"}
    assert set(ddi["half_life_days"]) == expected
    assert all(v > 0 for v in ddi["half_life_days"].values())


def test_bands_are_contiguous_from_0_to_100(ddi):
    bands = ddi["bands"]
    assert [b["name"] for b in bands] == ["low", "moderate", "high", "critical"]
    assert bands[0]["min"] == 0 and bands[-1]["max"] == 100
    for lower, upper in zip(bands, bands[1:]):
        assert lower["max"] == upper["min"]


def test_penalty_coefficients_and_floor(ddi):
    p = ddi["penalties"]
    assert p["contradiction_coefficient"] > p["uncertainty_coefficient"] > 0
    assert 0 < p["segment_divergence_floor_p1"] < 1


def test_gating_matches_business_rules(ddi):
    g = ddi["gating"]
    assert g["min_evidence_items"] == 3
    assert g["min_evidence_types"] == 2
    assert g["require_success_metric_evidence"] is True
    assert g["block_on_open_critical_dq_for_success_metric"] is True


def test_checklists_and_applicability_share_decision_types(ddi):
    assert set(ddi["coverage_checklists"]) == set(ddi["not_applicable_dimensions"])
    valid = set(ddi["positive_dimensions"])
    for dims in ddi["not_applicable_dimensions"].values():
        assert set(dims) <= valid
        assert len(valid - set(dims)) >= 1


def test_sensitivity_settings(ddi):
    s = ddi["sensitivity"]
    assert s["weight_multipliers"] == [0.5, 1.5]
    assert s["penalty_multipliers"] == [0.5, 1.5]
    assert s["robust_if_band_unchanged_share_at_least"] == 0.9


def test_nbe_actions_are_well_formed(nbe):
    bands = nbe["effort_bands_days"]
    assert bands == {"S": 1, "M": 3, "L": 8, "XL": 15}
    ids = [a["id"] for a in nbe["actions"]]
    assert len(ids) == len(set(ids)) >= 3
    for action in nbe["actions"]:
        assert action["effort_band"] in bands
        assert action["targets"]
    assert set(nbe["relevance_values"].values()) == {1.0, 0.7, 0.4}


def test_nbe_v0_2_differs_from_v0_1_only_in_version_and_the_blocker_dependency(nbe):
    """Day 4.1: v0.2 = v0.1 + `blocker_dependencies`. Every other value (bands, relevance, applicability, actions) is identical."""
    v2_file = CONFIG / "nbe" / "nbe_params_v0.2.yaml"
    v2 = yaml.safe_load(v2_file.read_text(encoding="utf-8"))
    assert v2["version"] == v2_file.stem == "nbe_params_v0.2" and v2["ddi_params_version"] == "ddi_params_v0.1"
    assert v2["blocker_dependencies"] == [{"blocker": b, "requires_resolved": "open_critical_dq"}
                                          for b in ("success_metric_evidence", "min_items", "min_types")]     # Day 4.1b widening
    assert "blocker_dependencies" not in nbe
    rest = {k: v for k, v in v2.items() if k not in ("version", "blocker_dependencies")}
    assert rest == {k: v for k, v in nbe.items() if k != "version"}
