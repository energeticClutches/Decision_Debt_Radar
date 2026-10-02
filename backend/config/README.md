# Versioned parameter sets

| File | Purpose | Spec |
|---|---|---|
| `ddi/ddi_params_v0.1.yaml` | DDI factors, half-lives, penalties, bands, gating, checklists, sensitivity | [docs/DDI-spec.md](../../docs/DDI-spec.md) |
| `nbe/nbe_params_v0.1.yaml` | Next Best Evidence effort bands, relevance values, action catalog | [docs/NBE-spec.md](../../docs/NBE-spec.md) |

Rules:
- Files are **immutable once used by an assessment**. To change any value, add a new version file (for example `ddi_params_v0.2.yaml`). Do not edit a released version.
- Every assessment stores the `params_version` it used.
- Values are proposed defaults and documented assumptions. DDI is a transparent evidence-risk heuristic, not an industry standard.
- **Hash registry (Day 3).** `params_hashes.json` records the SHA-256 of every released parameter file. `app.core.params` verifies the hash, the `version` field and the NBE-to-DDI version reference at load time and raises `ParamsError` on any mismatch. Assessments store the version and hash they used. `ddi_params_v0.1` and `nbe_params_v0.1` were amended in place on Day 3 before any assessment used them. After that they are immutable. The YAML files are marked `-text` in `.gitattributes` so line-ending conversion cannot change their hash.
- A structural test (`tests/unit/test_config_params.py`) and the loader tests (`tests/backend/test_params_loader.py`) guard the files.
