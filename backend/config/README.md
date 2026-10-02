# Versioned parameter sets

| File | Purpose | Spec |
|---|---|---|
| `ddi/ddi_params_v0.1.yaml` | DDI factors, half-lives, penalties, bands, gating, checklists, sensitivity | [docs/DDI-spec.md](../../docs/DDI-spec.md) |
| `nbe/nbe_params_v0.1.yaml` | Next Best Evidence original methodology: effort bands, relevance values, action catalog. Preserved unchanged, loadable for regression | [docs/NBE-spec.md](../../docs/NBE-spec.md) |
| `nbe/nbe_params_v0.2.yaml` | Day 4.1, the active NBE default: v0.1 plus the success-metric blocker dependency under an open critical DQ issue | [docs/NBE-spec.md](../../docs/NBE-spec.md) section 3a |
| `analytics/analytics_params_v0.1.yaml` | Day 4: generic analytics methods and thresholds (data quality, heterogeneity, experiment statistics, grading, stance). No organisation-specific value | [docs/day-4-implementation-notes.md](../../docs/day-4-implementation-notes.md) |
| `orgs/fitconnect/analytics_config.yaml` | Day 4: FitConnect tenant configuration (views, metrics, materiality, segment keys, funnels, comparison groups). Hashed; its hash is in `orgs/config_hashes.json` | [docs/day-4-implementation-notes.md](../../docs/day-4-implementation-notes.md) |

Rules:
- Files are **immutable once used by an assessment**. To change any value, add a new version file (for example `ddi_params_v0.2.yaml`). Do not edit a released version.
- Every assessment stores the `params_version` it used.
- Values are proposed defaults and documented assumptions. DDI is a transparent evidence-risk heuristic, not an industry standard.
- **Hash registry (Day 3).** `params_hashes.json` records the SHA-256 of every released parameter file. `app.core.params` verifies the hash, the `version` field and the NBE-to-DDI version reference at load time and raises `ParamsError` on any mismatch. Assessments store the version and hash they used. `ddi_params_v0.1` and `nbe_params_v0.1` were amended in place on Day 3 before any assessment used them. After that they are immutable. The YAML files are marked `-text` in `.gitattributes` so line-ending conversion cannot change their hash.
- **Day 4.** `params_hashes.json` gained one entry, `analytics_params_v0.1`; the `ddi` and `nbe` entries and files are unchanged (test T-GUARD-1). The tenant configuration is hashed through its own registry `orgs/config_hashes.json` and loaded with the same checks plus a match on the analytics parameter version.
- **Day 4.1.** `params_hashes.json` gained `nbe_params_v0.2`; every existing entry and file (`ddi`, `nbe` v0.1, analytics) is unchanged. `NBE_PARAMS_VERSION` defaults to `nbe_params_v0.2`. Day 4.1b widened v0.2's `blocker_dependencies` in place (it had not been committed or used by any stored assessment) to `success_metric_evidence`, `min_items` and `min_types`, all requiring `open_critical_dq` to be resolved; new hash `c46727dd…`. While the critical DQ issue is open, the Onboarding recommendation list is only the DQ fix (rank 1; it was rank 7 of 7 under v0.1).
- A structural test (`tests/unit/test_config_params.py`) and the loader tests (`tests/backend/test_params_loader.py`) guard the files.
