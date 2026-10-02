"""Fixed-seed reproducibility of the SYNTHETIC data generator (no database needed)."""

import json

from data.generator import config as C
from data.generator.__main__ import write_dataset

SMALL = 3000


def test_same_seed_produces_byte_identical_files(tmp_path):
    a = write_dataset(C.GenConfig(seed=123, users=SMALL), tmp_path / "a")["digests"]
    b = write_dataset(C.GenConfig(seed=123, users=SMALL), tmp_path / "b")["digests"]
    assert a == b
    assert len(a) == 10 and all(len(v) == 64 for v in a.values())


def test_different_seed_changes_the_data(tmp_path):
    a = write_dataset(C.GenConfig(seed=1, users=SMALL), tmp_path / "a")["digests"]
    b = write_dataset(C.GenConfig(seed=2, users=SMALL), tmp_path / "b")["digests"]
    assert a["events.csv"] != b["events.csv"] and a["users.csv"] != b["users.csv"]


def test_scale_is_configurable_and_manifest_is_synthetic(tmp_path):
    res = write_dataset(C.GenConfig(seed=C.DEFAULT_SEED, users=2000), tmp_path)
    manifest = json.loads((tmp_path / "manifest.json").read_text(encoding="utf-8"))
    assert res["meta"]["row_counts"]["users"] == 2000
    assert manifest["scale"]["users"] == 2000 and manifest["synthetic"] is True
    assert manifest["seed"] == C.DEFAULT_SEED
    assert "generated_at" not in manifest      # no wall-clock values, so the manifest is reproducible


def test_every_generated_row_is_labelled_synthetic(tmp_path):
    import csv
    write_dataset(C.GenConfig(seed=7, users=1500), tmp_path)
    for f in tmp_path.glob("*.csv"):
        with f.open(newline="", encoding="utf-8") as fh:
            rows = list(csv.DictReader(fh))
        assert rows and all(r["is_synthetic"] == "True" for r in rows), f.name


def test_tracked_manifest_matches_the_reproducibility_digest_for_default_seed():
    """data/manifest/ holds the canonical manifest and expected SHA-256 digests of the default seed output."""
    import hashlib
    from pathlib import Path
    d = Path(__file__).resolve().parents[2] / "data" / "manifest"
    manifest = d / "fitconnect_manifest.json"
    digests = json.loads((d / "fitconnect_digests.json").read_text(encoding="utf-8"))
    assert hashlib.sha256(manifest.read_bytes()).hexdigest() == digests["manifest.json"]
    parsed = json.loads(manifest.read_text(encoding="utf-8"))
    assert parsed["seed"] == C.DEFAULT_SEED and parsed["scale"]["users"] == C.GenConfig.users and parsed["synthetic"] is True
