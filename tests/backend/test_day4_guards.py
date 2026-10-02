"""Day-4 guards and configuration: T-GUARD-1 (DDI frozen, NBE v0.1 preserved; Day 4.1), T-GUARD-2 (scope guard), T-CFG-1 (hashed configuration)."""

from __future__ import annotations

import hashlib
import json
import shutil
import subprocess
from pathlib import Path

import pytest
import yaml

from app.analytics import queries as Q
from app.analytics.executor import ReadOnlyExecutor
from app.analytics.sql_guard import validate_select
from app.core.params import (
    load_analytics_params,
    load_ddi_params,
    load_tenant_config,
)
from app.domain.errors import ParamsError

ROOT = Path(__file__).resolve().parents[2]
APP = ROOT / "backend" / "app"
CONFIG = ROOT / "backend" / "config"
BASELINE = "f6209e9"


def git(*args: str) -> subprocess.CompletedProcess:
    return subprocess.run(["git", *args], cwd=ROOT, capture_output=True, text=True, timeout=60)


@pytest.fixture(scope="module")
def baseline_available() -> bool:
    try:
        probe = git("rev-parse", "--verify", f"{BASELINE}^{{commit}}")
    except (OSError, subprocess.SubprocessError):
        pytest.skip("git is not available")
    if probe.returncode != 0:
        pytest.skip(f"baseline commit {BASELINE} is not available in this checkout")
    return True


# ---------------------------------------------------------------- T-GUARD-1 (Day 4.1: DDI frozen; NBE v0.1 preserved, v0.2 added)
FROZEN_DDI = ["backend/app/domain/ddi", "backend/config/ddi"]
NBE_V01 = "backend/config/nbe/nbe_params_v0.1.yaml"


def test_t_guard_1_ddi_is_unchanged_against_the_baseline(baseline_available):
    diff = git("diff", BASELINE, "--stat", "--", *FROZEN_DDI)
    assert diff.returncode == 0, diff.stderr
    assert diff.stdout.strip() == "", f"the frozen DDI paths changed:\n{diff.stdout}"
    untracked = git("ls-files", "--others", "--exclude-standard", "--", *FROZEN_DDI)
    assert untracked.stdout.strip() == "", f"new files appeared in the frozen DDI paths:\n{untracked.stdout}"


def test_t_guard_1_nbe_v0_1_is_unchanged_and_the_only_new_nbe_config_is_v0_2(baseline_available):
    diff = git("diff", BASELINE, "--stat", "--", NBE_V01)
    assert diff.returncode == 0, diff.stderr
    assert diff.stdout.strip() == "", f"nbe_params_v0.1.yaml changed:\n{diff.stdout}"
    tracked = set(git("ls-tree", "-r", "--name-only", BASELINE, "--", "backend/config/nbe").stdout.split())
    assert tracked == {NBE_V01}
    new = set(git("ls-files", "--others", "--exclude-standard", "--", "backend/config/nbe").stdout.split())
    assert new <= {"backend/config/nbe/nbe_params_v0.2.yaml"}, f"unexpected new NBE config files: {new}"


def test_t_guard_1_nbe_code_changes_are_confined_to_the_params_reader_and_the_engine(baseline_available):
    """backend/app/domain/nbe may differ from the baseline only to read the v0.2 dependency configuration (params.py reads it,
    engine.py applies it). Output equality under v0.1 is proven by tests/backend/test_nbe_v02.py against golden output
    generated from the baseline code."""
    names = set(git("diff", BASELINE, "--name-only", "--", "backend/app/domain/nbe").stdout.split())
    assert names <= {"backend/app/domain/nbe/params.py", "backend/app/domain/nbe/engine.py"}, names
    untracked = git("ls-files", "--others", "--exclude-standard", "--", "backend/app/domain/nbe")
    assert untracked.stdout.strip() == ""


def test_t_guard_1_params_hashes_json_only_gains_the_analytics_and_nbe_v0_2_entries(baseline_available):
    old = json.loads(git("show", f"{BASELINE}:backend/config/params_hashes.json").stdout)
    new = json.loads((CONFIG / "params_hashes.json").read_text(encoding="utf-8"))
    assert {k: new[k] for k in old} == old, "an existing registry entry changed"
    assert set(new) - set(old) == {"analytics_params_v0.1", "nbe_params_v0.2"}
    for version, path in (("analytics_params_v0.1", CONFIG / "analytics" / "analytics_params_v0.1.yaml"),
                          ("nbe_params_v0.2", CONFIG / "nbe" / "nbe_params_v0.2.yaml")):
        assert new[version]["sha256"] == hashlib.sha256(path.read_bytes()).hexdigest()


def test_t_guard_1_the_ddi_and_nbe_files_still_match_their_registered_hashes():
    from app.core.params import load_nbe_params
    ddi = load_ddi_params()
    assert ddi.content_hash == "fd2541522b34f0fa2344076048f656fee8df8e9023148445fe53b3c7c119bcee"
    assert load_nbe_params("nbe_params_v0.1", ddi_params=ddi).content_hash == (
        "8a7c730edb77fc7b7f69cce487bce99fba5ace660f1c028c8cb6692221546ff7")
    assert load_nbe_params("nbe_params_v0.2", ddi_params=ddi).content_hash == (
        "c46727dd40fc642c01ea1cb490b346e41242dce11823bc55481210dc747658b2")


# ---------------------------------------------------------------- T-GUARD-2
FORBIDDEN_PACKAGES = ("anthropic", "agents", "openai")


def _imports(path: Path) -> set[str]:
    import ast
    tree = ast.parse(path.read_text(encoding="utf-8"))
    found = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            found.update(a.name.split(".")[0] for a in node.names)
        elif isinstance(node, ast.ImportFrom) and node.module and node.level == 0:
            found.add(node.module.split(".")[0])
    return found


def test_t_guard_2_anthropic_and_agents_are_never_imported_and_sqlglot_only_in_the_guard():
    sqlglot_users = []
    for path in APP.rglob("*.py"):
        mods = _imports(path)
        assert not (mods & set(FORBIDDEN_PACKAGES)), path
        if "sqlglot" in mods:
            sqlglot_users.append(path.relative_to(APP).as_posix())
    assert sqlglot_users == ["analytics/sql_guard.py"]


def test_t_guard_2_there_is_no_llm_sql_path():
    # the executor accepts catalogue templates only, never a free-form string
    with pytest.raises(TypeError):
        ReadOnlyExecutor().run("SELECT 1 LIMIT 1")          # type: ignore[arg-type]
    # every statement the analytics can run is built in the catalogue and passes the guard
    max_rows = 100_000
    templates = [
        Q.anchor_query(), Q.volume_events_query(), Q.signups_per_day_query(), Q.sequence_query(),
        Q.completeness_query("fc_.v_events", ["event_id", "user_id"], "event_ts"),
        Q.completeness_query("fc_.v_users", ["user_id"], None),
        Q.duplicates_query("fc_.v_events", ["user_id", "event_name", "event_ts"], "event_ts"),
        Q.duplicates_query("fc_.v_users", ["user_id"], None),
        Q.referential_query("fc_.v_events", "user_id", "event_ts"),
        Q.trend_query({"type": "event_within_days", "event": "x", "days": 7}),
        Q.comparison_query({"type": "event_after_days", "event": "x", "days": 90}, "engagement_style",
                           {"type": "event_users", "treatment_event": "y", "exclude_experiment_participants": True}),
        Q.comparison_query({"type": "subscription_status", "plan": "free_trial", "status": "trial_converted"}, "country",
                           {"type": "cohort_split", "split_date": "2026-04-01", "population": {"column": "country", "value": "CA"}}),
        Q.funnel_cohort_query(), Q.funnel_steps_query(), Q.experiment_assignments_query(), Q.experiment_outcomes_query(),
    ]
    for t in templates:
        validate_select(t.sql, max_rows=max_rows)
    # catalogue builders refuse an identifier or view that is not allow-listed
    with pytest.raises(ValueError):
        Q.completeness_query("fc_.users", ["user_id"], None)
    with pytest.raises(ValueError):
        Q.completeness_query("fc_.v_users", ["user_id; DROP TABLE x"], None)


def test_t_guard_2_product_code_never_reads_the_ground_truth_table():
    offenders = [str(p.relative_to(ROOT)) for base in (APP, CONFIG) for p in base.rglob("*")
                 if p.is_file() and p.suffix in (".py", ".yaml", ".json") and "feedback_ground_truth" in p.read_text(encoding="utf-8")]
    assert offenders == []


def test_t_guard_2_the_analytics_package_has_no_clock_reads_and_opens_no_transactions():
    """No wall clock anywhere in the analytics. The only transaction it opens is the read-only executor's own (section 9);
    the analytics never commits the caller's session (only services do)."""
    for path in (APP / "analytics").rglob("*.py"):
        text = path.read_text(encoding="utf-8")
        assert "datetime.now" not in text and "date.today" not in text and "utcnow" not in text, path
        assert ".commit()" not in text and ".rollback()" not in text, path
        if path.name != "executor.py":
            assert ".begin(" not in text, path


# ---------------------------------------------------------------- T-CFG-1
@pytest.fixture()
def config_copy(tmp_path):
    dst = tmp_path / "config"
    shutil.copytree(CONFIG, dst)
    return dst


def test_cfg_1_the_released_files_load_with_version_and_hash():
    p = load_analytics_params()
    t = load_tenant_config()
    assert p.version == "analytics_params_v0.1"
    assert p.content_hash == hashlib.sha256((CONFIG / "analytics" / "analytics_params_v0.1.yaml").read_bytes()).hexdigest()
    assert t.version == "fitconnect_analytics_config_v0.1" and t.analytics_params_version == p.version
    assert t.content_hash == hashlib.sha256((CONFIG / "orgs" / "fitconnect" / "analytics_config.yaml").read_bytes()).hexdigest()
    # the brief's values
    assert p.dq["window_days"] == 56 and p.dq["volume"] == {"warn_pct_drop": 0.25, "critical_pct_drop": 0.5}
    assert p.heterogeneity["min_segment_n"] == 500 and p.experiments["srm_alpha"] == 0.001
    assert {m: c["materiality"] for m, c in t.data["metrics"].items()} == {
        "d90_retention": 0.02, "activation_rate_7d": 0.02, "paid_conversion_rate": 0.02}
    assert t.data["segment_keys"] == {"d90_retention": "engagement_style", "activation_rate_7d": "platform",
                                      "paid_conversion_rate": "country"}


def test_cfg_1_an_edited_analytics_parameter_file_is_rejected(config_copy):
    path = config_copy / "analytics" / "analytics_params_v0.1.yaml"
    path.write_text(path.read_text(encoding="utf-8").replace("window_days: 56", "window_days: 57"), encoding="utf-8")
    with pytest.raises(ParamsError, match="registered hash"):
        load_analytics_params(config_dir=config_copy, registry_path=config_copy / "params_hashes.json")


def test_cfg_1_a_version_mismatch_or_missing_registration_is_rejected(config_copy):
    path = config_copy / "analytics" / "analytics_params_v0.1.yaml"
    raw = path.read_text(encoding="utf-8").replace("version: analytics_params_v0.1", "version: analytics_params_v0.2")
    path.write_text(raw, encoding="utf-8")
    registry = config_copy / "params_hashes.json"
    reg = json.loads(registry.read_text(encoding="utf-8"))
    reg["analytics_params_v0.1"]["sha256"] = hashlib.sha256(path.read_bytes()).hexdigest()       # hash matches, version field does not
    registry.write_text(json.dumps(reg), encoding="utf-8")
    with pytest.raises(ParamsError, match="version"):
        load_analytics_params(config_dir=config_copy, registry_path=registry)
    del reg["analytics_params_v0.1"]
    registry.write_text(json.dumps(reg), encoding="utf-8")
    with pytest.raises(ParamsError, match="not registered"):
        load_analytics_params(config_dir=config_copy, registry_path=registry)
    with pytest.raises(ParamsError, match="not found"):
        load_analytics_params("analytics_params_v9.9", config_dir=config_copy, registry_path=registry)


def test_cfg_1_an_edited_tenant_configuration_is_rejected(config_copy):
    path = config_copy / "orgs" / "fitconnect" / "analytics_config.yaml"
    path.write_text(path.read_text(encoding="utf-8").replace("materiality: 0.02", "materiality: 0.03", 1), encoding="utf-8")
    with pytest.raises(ParamsError, match="registered hash"):
        load_tenant_config(config_dir=config_copy)


def test_cfg_1_the_tenant_configuration_must_match_the_active_analytics_version(config_copy):
    path = config_copy / "orgs" / "fitconnect" / "analytics_config.yaml"
    raw = path.read_text(encoding="utf-8").replace("analytics_params_version: analytics_params_v0.1",
                                                    "analytics_params_version: analytics_params_v0.9")
    path.write_text(raw, encoding="utf-8")
    registry = config_copy / "orgs" / "config_hashes.json"
    reg = json.loads(registry.read_text(encoding="utf-8"))
    reg["fitconnect_analytics_config_v0.1"]["sha256"] = hashlib.sha256(path.read_bytes()).hexdigest()
    registry.write_text(json.dumps(reg), encoding="utf-8")
    with pytest.raises(ParamsError, match="analytics parameter version"):
        load_tenant_config(config_dir=config_copy)


def test_cfg_1_invalid_structure_is_rejected_at_load(config_copy):
    # a valid hash is not enough: the structure is validated (here: a critical threshold below the warn threshold)
    path = config_copy / "analytics" / "analytics_params_v0.1.yaml"
    raw = yaml.safe_load(path.read_text(encoding="utf-8"))
    raw["dq"]["volume"]["critical_pct_drop"] = 0.1
    path.write_text(yaml.safe_dump(raw), encoding="utf-8")
    registry = config_copy / "params_hashes.json"
    reg = json.loads(registry.read_text(encoding="utf-8"))
    reg["analytics_params_v0.1"]["sha256"] = hashlib.sha256(path.read_bytes()).hexdigest()
    registry.write_text(json.dumps(reg), encoding="utf-8")
    with pytest.raises(ParamsError, match="warn <= critical"):
        load_analytics_params(config_dir=config_copy, registry_path=registry)


def test_cfg_1_tenant_values_live_only_in_the_tenant_file():
    """FitConnect-specific values (metric, event and segment names) are never in core code or in the generic parameters."""
    generic = (CONFIG / "analytics" / "analytics_params_v0.1.yaml").read_text(encoding="utf-8")
    for word in ("fitconnect", "d90_retention", "onboarding", "engagement_style", "ai_coach", "app_open"):
        assert word not in generic.lower(), word
    for path in (APP / "analytics").rglob("*.py"):
        text = path.read_text(encoding="utf-8")
        for word in ("d90_retention", "activation_rate_7d", "paid_conversion_rate", "engagement_style", "onboarding_completed",
                     "ai_coach_session", "challenge_joined", "app_open"):
            assert word not in text, (path.name, word)
