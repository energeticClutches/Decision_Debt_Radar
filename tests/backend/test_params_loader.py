"""Parameter loader: version and content-hash validation (brief test 13)."""

from __future__ import annotations

import json
import shutil
from pathlib import Path

import pytest

from app.core.params import CONFIG_DIR, REGISTRY_FILE, load_ddi_params, load_nbe_params, sha256_file
from app.domain.errors import ParamsError


@pytest.fixture()
def cfg(tmp_path: Path):
    """A private copy of the config directory and registry that tests may tamper with."""
    dst = tmp_path / "config"
    shutil.copytree(CONFIG_DIR, dst)
    return dst, dst / "params_hashes.json"


def test_active_parameters_load_with_the_registered_hash():
    ddi = load_ddi_params()
    nbe = load_nbe_params(ddi_params=ddi)
    registry = json.loads(REGISTRY_FILE.read_text(encoding="utf-8"))
    assert ddi.version == "ddi_params_v0.1" and ddi.content_hash == registry["ddi_params_v0.1"]["sha256"]
    assert nbe.version == "nbe_params_v0.2" and nbe.content_hash == registry["nbe_params_v0.2"]["sha256"]     # Day 4.1: v0.2 is the default
    assert nbe.ddi_params_version == ddi.version
    old = load_nbe_params("nbe_params_v0.1", ddi_params=ddi)                                                    # v0.1 stays loadable
    assert old.version == "nbe_params_v0.1" and old.content_hash == registry["nbe_params_v0.1"]["sha256"]
    assert ddi.content_hash == sha256_file(CONFIG_DIR / "ddi" / "ddi_params_v0.1.yaml")


def test_edited_file_fails_the_hash_check(cfg):
    config_dir, registry = cfg
    f = config_dir / "ddi" / "ddi_params_v0.1.yaml"
    f.write_bytes(f.read_bytes().replace(b"small_n_threshold: 100", b"small_n_threshold: 101"))
    with pytest.raises(ParamsError, match="registered hash"):
        load_ddi_params(config_dir=config_dir, registry_path=registry)


def test_version_field_must_match_the_requested_version(cfg):
    config_dir, registry = cfg
    f = config_dir / "ddi" / "ddi_params_v0.1.yaml"
    f.write_bytes(f.read_bytes().replace(b"version: ddi_params_v0.1", b"version: ddi_params_v9.9", 1))
    reg = json.loads(registry.read_text(encoding="utf-8"))
    reg["ddi_params_v0.1"]["sha256"] = sha256_file(f)          # hash is consistent, version field is not
    registry.write_text(json.dumps(reg), encoding="utf-8")
    with pytest.raises(ParamsError, match="version"):
        load_ddi_params(config_dir=config_dir, registry_path=registry)


def test_unregistered_or_missing_version_raises(cfg):
    config_dir, registry = cfg
    shutil.copy(config_dir / "ddi" / "ddi_params_v0.1.yaml", config_dir / "ddi" / "ddi_params_v0.2.yaml")
    with pytest.raises(ParamsError, match="not registered"):
        load_ddi_params("ddi_params_v0.2", config_dir=config_dir, registry_path=registry)
    with pytest.raises(ParamsError, match="not found"):
        load_ddi_params("ddi_params_v7", config_dir=config_dir, registry_path=registry)


@pytest.mark.parametrize("version", ["nbe_params_v0.1", "nbe_params_v0.2"])
def test_nbe_file_must_reference_the_active_ddi_version(cfg, version):
    config_dir, registry = cfg
    ddi = load_ddi_params(config_dir=config_dir, registry_path=registry)
    f = config_dir / "nbe" / f"{version}.yaml"
    f.write_bytes(f.read_bytes().replace(b"ddi_params_version: ddi_params_v0.1", b"ddi_params_version: ddi_params_v0.2"))
    reg = json.loads(registry.read_text(encoding="utf-8"))
    reg[version]["sha256"] = sha256_file(f)
    registry.write_text(json.dumps(reg), encoding="utf-8")
    with pytest.raises(ParamsError, match="reference DDI version"):
        load_nbe_params(version, ddi_params=ddi, config_dir=config_dir, registry_path=registry)


def test_nbe_v0_2_fails_on_a_hash_or_version_mismatch(cfg):
    config_dir, registry = cfg
    ddi = load_ddi_params(config_dir=config_dir, registry_path=registry)
    f = config_dir / "nbe" / "nbe_params_v0.2.yaml"
    original = f.read_bytes()
    f.write_bytes(original + b"# edited after registration\n")
    with pytest.raises(ParamsError, match="registered hash"):
        load_nbe_params("nbe_params_v0.2", ddi_params=ddi, config_dir=config_dir, registry_path=registry)
    f.write_bytes(original.replace(b"version: nbe_params_v0.2", b"version: nbe_params_v9.9", 1))
    reg = json.loads(registry.read_text(encoding="utf-8"))
    reg["nbe_params_v0.2"]["sha256"] = sha256_file(f)                      # hash is consistent, the version field is not
    registry.write_text(json.dumps(reg), encoding="utf-8")
    with pytest.raises(ParamsError, match="does not match the requested version"):
        load_nbe_params("nbe_params_v0.2", ddi_params=ddi, config_dir=config_dir, registry_path=registry)


def test_parameter_amendments_of_the_day_3_brief_are_present():
    ddi = load_ddi_params()
    assert ddi.small_n_threshold == 100 and ddi.n_required == 1000 and ddi.materiality_threshold == 0.02
    assert ddi.default_relevance == 0.5 and ddi.default_segment_coverage == 0.5
    assert ddi.default_power_factor == 0.5 and ddi.default_informativeness == 0.3
    assert ddi.direction_majority_share == 0.6 and ddi.direction_min_bearing_items == 2
    assert ddi.bands[-1].name == "critical" and ddi.bands[-1].max_inclusive is True
    nbe = load_nbe_params(ddi_params=ddi)
    assert all(a.id != "clears_heterogeneity_floor" for a in nbe.actions)
    assert nbe.applicability["freshness_threshold"] == 0.5 and nbe.applicability["concentration_threshold"] == 0.5
