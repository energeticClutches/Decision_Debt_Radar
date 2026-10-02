"""Parameter loader with version and content-hash validation (R4, brief section 3.2).

Each parameter file is hashed (SHA-256 of its bytes). The loader raises ParamsError when
  - the file does not exist,
  - the committed registry (backend/config/params_hashes.json) has no entry for the version,
  - the file hash differs from the registry entry (the file was edited after registration),
  - the `version` field differs from the requested version or the file name,
  - an NBE file references a DDI version other than the DDI version being used.
A released parameter version is never edited. A new version is a new file and a new registry entry.
"""

from __future__ import annotations

import hashlib
import json
from functools import lru_cache
from pathlib import Path

import yaml

from app.analytics.config import AnalyticsParams, TenantConfig
from app.core.config import get_settings
from app.domain.ddi.params import DdiParams
from app.domain.errors import ParamsError
from app.domain.nbe.params import NbeParams

CONFIG_DIR = Path(__file__).resolve().parents[2] / "config"
REGISTRY_FILE = CONFIG_DIR / "params_hashes.json"
# Tenant (organisation) configuration files are hashed too. Their registry is separate from params_hashes.json,
# which holds only the versioned engine parameter sets (Day 4 may only add analytics_params_v0.1 to it).
ORG_REGISTRY_FILE = CONFIG_DIR / "orgs" / "config_hashes.json"


def sha256_file(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _load_verified(kind: str, version: str, config_dir: Path, registry_path: Path) -> tuple[dict, str]:
    path = config_dir / kind / f"{version}.yaml"
    if not path.is_file():
        raise ParamsError(f"{kind.upper()} parameter file not found: {path.name}")
    try:
        registry = json.loads(registry_path.read_text(encoding="utf-8"))
    except (OSError, ValueError) as exc:
        raise ParamsError(f"parameter hash registry unreadable: {exc}") from exc
    entry = registry.get(version)
    if not entry or "sha256" not in entry:
        raise ParamsError(f"parameter version {version} is not registered in params_hashes.json")
    actual = sha256_file(path)
    if actual != entry["sha256"]:
        raise ParamsError(
            f"parameter file {path.name} does not match its registered hash (expected {entry['sha256'][:12]}..., "
            f"got {actual[:12]}...). Released parameter versions are immutable: create a new version instead.")
    raw = yaml.safe_load(path.read_text(encoding="utf-8"))
    if not isinstance(raw, dict) or raw.get("version") != version:
        raise ParamsError(f"{path.name}: version field {raw.get('version') if isinstance(raw, dict) else None!r} "
                          f"does not match the requested version {version}")
    return raw, actual


def load_ddi_params(version: str | None = None, *, config_dir: Path | None = None,
                    registry_path: Path | None = None) -> DdiParams:
    version = version or get_settings().ddi_params_version
    raw, digest = _load_verified("ddi", version, config_dir or CONFIG_DIR, registry_path or REGISTRY_FILE)
    return DdiParams.from_mapping(raw, digest)


def load_nbe_params(version: str | None = None, *, ddi_params: DdiParams | None = None,
                    config_dir: Path | None = None, registry_path: Path | None = None) -> NbeParams:
    """`ddi_params` is the active DDI parameter set. The NBE file must reference its version."""
    version = version or get_settings().nbe_params_version
    ddi_params = ddi_params or load_ddi_params(config_dir=config_dir, registry_path=registry_path)
    raw, digest = _load_verified("nbe", version, config_dir or CONFIG_DIR, registry_path or REGISTRY_FILE)
    params = NbeParams.from_mapping(raw, digest)
    if params.ddi_params_version != ddi_params.version:
        raise ParamsError(f"NBE parameters {params.version} reference DDI version {params.ddi_params_version}, "
                          f"but the active DDI version is {ddi_params.version}")
    return params


def load_analytics_params(version: str | None = None, *, config_dir: Path | None = None,
                          registry_path: Path | None = None) -> AnalyticsParams:
    """Generic analytics parameters (Day 4). Same version, hash and ParamsError checks as the DDI file."""
    version = version or get_settings().analytics_params_version
    raw, digest = _load_verified("analytics", version, config_dir or CONFIG_DIR, registry_path or REGISTRY_FILE)
    return AnalyticsParams.from_mapping(raw, digest)


def load_tenant_config(org_key: str | None = None, *, analytics_params: AnalyticsParams | None = None,
                       config_dir: Path | None = None, registry_path: Path | None = None) -> TenantConfig:
    """Tenant analytics configuration (orgs/<org_key>/analytics_config.yaml), hash-verified against its registry.

    The file must declare the analytics parameter version it was written for, which must be the active one."""
    org_key = org_key or get_settings().tenant_config_key
    base = config_dir or CONFIG_DIR
    path = base / "orgs" / org_key / "analytics_config.yaml"
    if not path.is_file():
        raise ParamsError(f"tenant analytics configuration not found for '{org_key}': {path.name}")
    try:
        raw = yaml.safe_load(path.read_text(encoding="utf-8"))
    except yaml.YAMLError as exc:
        raise ParamsError(f"tenant analytics configuration is not valid YAML: {exc}") from exc
    if not isinstance(raw, dict) or not raw.get("version"):
        raise ParamsError(f"{path.name}: missing version field")
    registry_file = registry_path or (base / "orgs" / "config_hashes.json")
    try:
        registry = json.loads(registry_file.read_text(encoding="utf-8"))
    except (OSError, ValueError) as exc:
        raise ParamsError(f"tenant configuration hash registry unreadable: {exc}") from exc
    entry = registry.get(raw["version"])
    if not entry or "sha256" not in entry:
        raise ParamsError(f"tenant configuration {raw['version']} is not registered in {registry_file.name}")
    actual = sha256_file(path)
    if actual != entry["sha256"]:
        raise ParamsError(
            f"tenant configuration {path.name} does not match its registered hash (expected {entry['sha256'][:12]}..., "
            f"got {actual[:12]}...). Released configuration versions are immutable: create a new version instead.")
    analytics_params = analytics_params or load_analytics_params(config_dir=config_dir)
    if raw.get("analytics_params_version") != analytics_params.version:
        raise ParamsError(f"tenant configuration {raw['version']} was written for {raw.get('analytics_params_version')}, "
                          f"but the active analytics parameter version is {analytics_params.version}")
    if raw.get("org_key") != org_key:
        raise ParamsError(f"tenant configuration {raw['version']} declares org_key {raw.get('org_key')!r}, expected {org_key!r}")
    return TenantConfig.from_mapping(raw, actual)


@lru_cache
def get_analytics_params() -> AnalyticsParams:
    return load_analytics_params()


@lru_cache
def get_tenant_config() -> TenantConfig:
    return load_tenant_config(analytics_params=get_analytics_params())


@lru_cache
def get_ddi_params() -> DdiParams:
    return load_ddi_params()


@lru_cache
def get_nbe_params() -> NbeParams:
    return load_nbe_params(ddi_params=get_ddi_params())
