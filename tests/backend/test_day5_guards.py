"""Day-5 guards (G1, G2, G3) and the hashed configuration, prompts and fixtures.

G1  DDI v0.1 and NBE v0.2 are frozen against the Day-4.1 baseline 65caec6: zero diff in the four frozen paths.
G2  the scope guard: `anthropic` only in backend/app/llm/anthropic_client.py, no agent framework, sqlglot only in the SQL guard.
G3  product code, prompts and configuration never read the evaluation ground-truth labels.
"""

from __future__ import annotations

import ast
import hashlib
import json
import shutil
import subprocess
from pathlib import Path

import pytest
import yaml

from app.core.params import (
    load_analytics_params,
    load_tenant_config,
)
from app.domain.errors import ParamsError
from app.llm.prompts import PROMPT_IDS, load_prompt

ROOT = Path(__file__).resolve().parents[2]
APP = ROOT / "backend" / "app"
CONFIG = ROOT / "backend" / "config"
PROMPTS = ROOT / "prompts"
BASELINE = "65caec6"
FROZEN = ["backend/app/domain/ddi", "backend/app/domain/nbe", "backend/config/ddi", "backend/config/nbe"]


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


# ================================================================ G1
def test_g1_ddi_and_nbe_code_and_config_have_zero_diff_against_65caec6(baseline_available):
    stat = git("diff", BASELINE, "--stat", "--", *FROZEN)
    assert stat.returncode == 0, stat.stderr
    assert stat.stdout.strip() == "", f"a frozen path changed:\n{stat.stdout}"
    names = git("diff", BASELINE, "--name-only", "--", *FROZEN)
    assert names.stdout.strip() == ""
    untracked = git("ls-files", "--others", "--exclude-standard", "--", *FROZEN)
    assert untracked.stdout.strip() == "", f"new files appeared in a frozen path:\n{untracked.stdout}"
    staged = git("diff", "--cached", BASELINE, "--name-only", "--", *FROZEN)
    assert staged.stdout.strip() == ""


def test_g1_released_configuration_versions_are_immutable(baseline_available):
    """Existing versioned files and their registered hashes are unchanged; Day 5 only ADDS new versions."""
    for rel in ("backend/config/analytics/analytics_params_v0.1.yaml", "backend/config/orgs/fitconnect/analytics_config.yaml",
                "backend/config/ddi/ddi_params_v0.1.yaml", "backend/config/nbe/nbe_params_v0.1.yaml", "backend/config/nbe/nbe_params_v0.2.yaml"):
        assert git("diff", BASELINE, "--stat", "--", rel).stdout.strip() == "", rel
    old = json.loads(git("show", f"{BASELINE}:backend/config/params_hashes.json").stdout)
    new = json.loads((CONFIG / "params_hashes.json").read_text(encoding="utf-8"))
    assert {k: new[k] for k in old} == old, "an existing params registry entry changed"
    assert set(new) - set(old) == {"analytics_params_v0.2"}
    old_org = json.loads(git("show", f"{BASELINE}:backend/config/orgs/config_hashes.json").stdout)
    new_org = json.loads((CONFIG / "orgs" / "config_hashes.json").read_text(encoding="utf-8"))
    assert {k: new_org[k] for k in old_org} == old_org, "an existing tenant registry entry changed"
    assert set(new_org) - set(old_org) == {"fitconnect_analytics_config_v0.2"}
    for version, entry in {**new, **new_org}.items():
        path = CONFIG / entry["file"]
        assert hashlib.sha256(path.read_bytes()).hexdigest() == entry["sha256"], version


# ================================================================ G2
FORBIDDEN_AGENT_FRAMEWORKS = {"langchain", "langchain_core", "langchain_anthropic", "langgraph", "crewai", "autogen", "llama_index",
                              "haystack", "semantic_kernel", "agents", "openai", "smolagents", "pydantic_ai", "dspy"}


def _imports(path: Path) -> set[str]:
    tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
    found: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            found.update(a.name.split(".")[0] for a in node.names)
        elif isinstance(node, ast.ImportFrom) and node.module and node.level == 0:
            found.add(node.module.split(".")[0])
    return found


def test_g2_anthropic_only_in_the_client_module_sqlglot_only_in_the_sql_guard_and_no_agent_framework():
    anthropic_users, sqlglot_users = [], []
    files = list(APP.rglob("*.py"))
    assert len(files) > 60
    for path in files:
        mods = _imports(path)
        rel = path.relative_to(APP).as_posix()
        if "anthropic" in mods:
            anthropic_users.append(rel)
        if "sqlglot" in mods:
            sqlglot_users.append(rel)
        assert not (mods & FORBIDDEN_AGENT_FRAMEWORKS), (rel, mods & FORBIDDEN_AGENT_FRAMEWORKS)
        text = path.read_text(encoding="utf-8")
        for name in ("anthropic", "sqlglot", "agents"):
            assert f'import_module("{name}' not in text and f"__import__('{name}" not in text, (rel, name)
    assert anthropic_users == ["llm/anthropic_client.py"]
    assert sqlglot_users == ["analytics/sql_guard.py"]
    for path in list((ROOT / "agents").rglob("*.py")) + list((ROOT / "scripts").rglob("*.py")):
        assert not (_imports(path) & (FORBIDDEN_AGENT_FRAMEWORKS - {"agents"})), path


def test_g2_the_llm_package_has_no_database_or_sql_tooling_and_the_client_module_is_lazy():
    """The model gets no database access and no tool: the client modules import neither sqlalchemy nor the SQL guard."""
    for name in ("client.py", "anthropic_client.py"):
        mods = _imports(APP / "llm" / name)
        assert not (mods & {"sqlalchemy", "psycopg", "sqlglot"}), name
    init = (APP / "llm" / "__init__.py").read_text(encoding="utf-8")
    assert init.index("def get_llm_client") < init.index("from app.llm.anthropic_client import")      # imported only inside the factory
    for path in APP.rglob("*.py"):
        rel = path.relative_to(APP).as_posix()
        if rel in ("llm/__init__.py", "llm/anthropic_client.py"):
            continue
        tree = ast.parse(path.read_text(encoding="utf-8"))
        for node in ast.walk(tree):
            if isinstance(node, ast.ImportFrom) and node.module:
                assert "anthropic_client" not in node.module, rel


def test_g2_there_is_no_llm_written_sql_and_no_generic_agent_endpoint():
    from app.main import app
    paths = set(app.openapi()["paths"])
    assert not [p for p in paths if "agent" in p or "llm" in p or "prompt" in p or "/sql" in p]
    assert {"/decisions/{decision_id}/customer-evidence", "/evidence/{evidence_id}/approval", "/assessments/{assessment_id}/syntheses",
            "/assessments/{assessment_id}/briefs", "/briefs/{brief_id}"} <= paths


# ================================================================ G3
def test_g3_product_code_prompts_and_configuration_never_name_the_ground_truth_table():
    offenders = []
    for base in (APP, CONFIG, PROMPTS, ROOT / "agents", ROOT / "scripts"):
        for p in base.rglob("*"):
            if p.is_file() and p.suffix in (".py", ".yaml", ".yml", ".json", ".md", ".txt") and ".venv" not in p.parts:
                if "feedback_ground_truth" in p.read_text(encoding="utf-8"):
                    offenders.append(str(p.relative_to(ROOT)))
    assert offenders == []


def test_g3_the_sql_guard_does_not_allow_the_ground_truth_table_and_the_candidate_query_cannot_name_it():
    from app.analytics import queries as Q
    from app.analytics.sql_guard import ALLOWED_TABLES, SqlRejected, validate_select
    assert not any("ground_truth" in t for t in ALLOWED_TABLES)
    with pytest.raises(SqlRejected):
        validate_select("SELECT theme FROM fc_.feedback_ground_truth LIMIT 10", max_rows=100)
    with pytest.raises(ValueError):
        Q.feedback_candidates_query({"view": "fc_.feedback_ground_truth", "id_column": "feedback_id", "text_column": "theme",
                                     "ts_column": "created_at", "source_column": "source", "user_column": "user_id"}, None)
    tenant = __import__("app.core.params", fromlist=["get_tenant_config"]).get_tenant_config()
    sql = Q.feedback_candidates_query(tenant.customer_feedback(), "engagement_style").sql
    assert "ground_truth" not in sql and "fc_.v_feedback" in sql
    validate_select(sql, max_rows=100_000)


def test_g3_theme_names_do_not_copy_the_ground_truth_labels_and_the_stub_never_touches_the_database():
    from data.generator.feedback import THEMES                         # the label vocabulary of the generator (test-only)
    tenant = __import__("app.core.params", fromlist=["get_tenant_config"]).get_tenant_config()
    names = {t.theme for scen in ("ai_coach", "community", "onboarding", "pricing") for t in tenant.customer_taxonomy(scen).themes}
    assert len(names) == 9
    assert names.isdisjoint(set(THEMES)), names & set(THEMES)
    stub = (ROOT / "tests" / "fixtures" / "llm" / "stub_classifier.py").read_text(encoding="utf-8")
    assert "ground_truth" not in stub and "sqlalchemy" not in stub and "psycopg" not in stub and "feedback_ground" not in stub
    assert _imports(ROOT / "tests" / "fixtures" / "llm" / "stub_classifier.py") <= {"__future__", "html", "json", "re", "app"}


def test_g3_the_record_script_never_reads_the_ground_truth_and_does_not_run_on_import():
    script = ROOT / "scripts" / "record_llm_fixtures.py"
    assert script.is_file()
    text = script.read_text(encoding="utf-8")
    assert "ground_truth" not in text and 'if __name__ == "__main__"' in text
    assert "recorded_model_output" in text and "ANTHROPIC_API_KEY" in text


# ================================================================ configuration and prompts
def test_day5_config_versions_load_with_their_hashes_and_v0_1_is_still_loadable():
    p2 = load_analytics_params()
    assert p2.version == "analytics_params_v0.2"
    assert p2.content_hash == hashlib.sha256((CONFIG / "analytics" / "analytics_params_v0.2.yaml").read_bytes()).hexdigest()
    assert dict(p2.customer) == {"min_theme_mentions": 30, "grade_c_min_mentions": 100, "grade_c_min_source_types": 2,
                                 "sample_quotes_per_insight": 5}
    llm = p2.llm
    assert llm["temperature"] == 0 and llm["timeout_s"] == 60 and llm["max_retries"] == 1 and llm["classification_batch_size"] == 50
    assert set(llm["max_output_tokens"]) == {"classify", "synthesize", "review"}
    p1 = load_analytics_params("analytics_params_v0.1")
    assert p1.version == "analytics_params_v0.1"
    with pytest.raises(ParamsError, match="no customer section"):
        _ = p1.customer
    # v0.2 = v0.1 plus the customer and llm sections: every other value is unchanged
    raw1, raw2 = dict(p1.data), dict(p2.data)
    assert {k: v for k, v in raw2.items() if k not in ("customer", "llm", "version")} == {k: v for k, v in raw1.items() if k != "version"}
    t2 = load_tenant_config()
    assert t2.version == "fitconnect_analytics_config_v0.2" and t2.analytics_params_version == "analytics_params_v0.2"
    assert t2.content_hash == hashlib.sha256((CONFIG / "orgs" / "fitconnect" / "analytics_config_v0.2.yaml").read_bytes()).hexdigest()
    t1 = load_tenant_config(version="fitconnect_analytics_config_v0.1", analytics_params=p1)
    assert t1.analytics_params_version == "analytics_params_v0.1"
    assert {k: v for k, v in t2.data.items() if k not in ("customer_feedback", "customer_taxonomy", "version", "analytics_params_version")} == \
           {k: v for k, v in t1.data.items() if k not in ("version", "analytics_params_version")}


def test_day5_stance_map_is_human_authored_in_the_tenant_config_as_proposed():
    t = load_tenant_config()
    stance = {s: {x.theme: x.stance for x in t.customer_taxonomy(s).themes} for s in ("ai_coach", "community", "onboarding", "pricing")}
    assert stance == {
        "ai_coach": {"coach_helpful": "supports", "coach_generic_or_wrong": "contradicts", "coach_indifferent": "neutral"},
        "community": {"challenges_motivating": "supports", "notifications_unwanted": "contradicts", "challenges_indifferent": "neutral"},
        "onboarding": {"setup_blocked": "supports"},
        "pricing": {"price_too_high": "contradicts", "worth_the_price": "supports"}}
    assert t.customer_taxonomy("nonexistent") is None
    a, b = t.customer_taxonomy("pricing"), t.customer_taxonomy("pricing")
    assert a.taxonomy_id == b.taxonomy_id and a.taxonomy_id.startswith("fitconnect_pricing_taxonomy_v0.1#")


@pytest.fixture()
def config_copy(tmp_path):
    dst = tmp_path / "config"
    shutil.copytree(CONFIG, dst)
    return dst


def test_day5_an_edited_v0_2_parameter_file_or_tenant_file_is_rejected(config_copy):
    path = config_copy / "analytics" / "analytics_params_v0.2.yaml"
    path.write_text(path.read_text(encoding="utf-8").replace("min_theme_mentions: 30", "min_theme_mentions: 31"), encoding="utf-8")
    with pytest.raises(ParamsError, match="registered hash"):
        load_analytics_params(config_dir=config_copy, registry_path=config_copy / "params_hashes.json")
    tpath = config_copy / "orgs" / "fitconnect" / "analytics_config_v0.2.yaml"
    tpath.write_text(tpath.read_text(encoding="utf-8").replace("stance: contradicts", "stance: supports", 1), encoding="utf-8")
    with pytest.raises(ParamsError, match="registered hash"):
        load_tenant_config(config_dir=config_copy)


def test_day5_invalid_customer_or_llm_sections_are_rejected_at_load(config_copy):
    path = config_copy / "analytics" / "analytics_params_v0.2.yaml"
    raw = yaml.safe_load(path.read_text(encoding="utf-8"))
    raw["llm"]["temperature"] = 0.7
    path.write_text(yaml.safe_dump(raw), encoding="utf-8")
    registry = config_copy / "params_hashes.json"
    reg = json.loads(registry.read_text(encoding="utf-8"))
    reg["analytics_params_v0.2"]["sha256"] = hashlib.sha256(path.read_bytes()).hexdigest()
    registry.write_text(json.dumps(reg), encoding="utf-8")
    with pytest.raises(ParamsError, match="temperature"):
        load_analytics_params(config_dir=config_copy, registry_path=registry)


def test_day5_the_prompts_are_hashed_versioned_and_state_that_customer_text_is_data():
    for pid in PROMPT_IDS:
        p = load_prompt(pid, "v0.1")
        assert p.version == "v0.1" and p.sha256 == hashlib.sha256((PROMPTS / "v0.1" / f"{pid}.md").read_bytes()).hexdigest()
        assert "<untrusted_customer_text>" in p.text and "never an instruction" in p.text and "SYNTHETIC" in p.text
        assert "ground_truth" not in p.text
    assert "never recommend" in load_prompt("synthesize").text.lower() or "NEVER recommend" in load_prompt("synthesize").text
    registry = json.loads((PROMPTS / "prompt_hashes.json").read_text(encoding="utf-8"))
    assert set(registry["v0.1"]) == set(PROMPT_IDS)


def test_day5_a_tampered_unregistered_or_misdeclared_prompt_is_rejected(tmp_path):
    base = tmp_path / "prompts"
    shutil.copytree(PROMPTS, base)
    (base / "v0.1" / "classify.md").write_text((base / "v0.1" / "classify.md").read_text(encoding="utf-8") + "\nextra", encoding="utf-8")
    with pytest.raises(ParamsError, match="registered hash"):
        load_prompt("classify", "v0.1", prompts_dir=base)
    with pytest.raises(ParamsError, match="not registered"):
        load_prompt("classify", "v9.9", prompts_dir=base)
    with pytest.raises(ParamsError, match="not registered"):
        load_prompt("nonexistent", "v0.1", prompts_dir=base)
    # a hash that matches but a header that declares another prompt
    shutil.copytree(PROMPTS, tmp_path / "p2")
    swapped = (tmp_path / "p2" / "v0.1" / "review.md").read_text(encoding="utf-8").replace("<!-- prompt: review v0.1 -->", "<!-- prompt: classify v0.1 -->")
    (tmp_path / "p2" / "v0.1" / "review.md").write_text(swapped, encoding="utf-8")
    reg = json.loads((tmp_path / "p2" / "prompt_hashes.json").read_text(encoding="utf-8"))
    reg["v0.1"]["review"]["sha256"] = hashlib.sha256((tmp_path / "p2" / "v0.1" / "review.md").read_bytes()).hexdigest()
    (tmp_path / "p2" / "prompt_hashes.json").write_text(json.dumps(reg), encoding="utf-8")
    with pytest.raises(ParamsError, match="first line"):
        load_prompt("review", "v0.1", prompts_dir=tmp_path / "p2")


def test_day5_every_stub_fixture_carries_the_stub_provenance_and_a_stub_model_name():
    files = sorted((ROOT / "tests" / "fixtures" / "llm" / "recorded").glob("*.json"))
    assert len(files) == 8
    for f in files:
        data = json.loads(f.read_text(encoding="utf-8"))
        assert data["provenance"] == "stub_not_model_output", f.name
        assert data["model"].startswith("stub:"), f.name
        assert "HAND-AUTHORED, not model output" in data["note"], f.name
    from stub_classifier import MODEL
    assert MODEL.startswith("stub:")
