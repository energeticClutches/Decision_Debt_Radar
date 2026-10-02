"""Storing analyses as analysis_results rows (D4-15, D4-16). The analytics layer writes analysis_results only.

An analysis row records the executed query, the parameters (including the analytics-parameter and tenant-configuration hashes),
n, the result, the limitations and the DQ status of the data it read. Rows are historical (insert-only). The IDENTITY of an
analysis, sha256(decision | analysis_type | metric_id | experiment-or-segment-or-cohort key | analysis_params_hash), does not
include the data: a re-run with new data keeps the identity and changes the source fingerprint. A re-run whose content is
identical to the latest row of the same identity reuses that row instead of inserting a duplicate.
"""

from __future__ import annotations

import hashlib
import json
import uuid
from dataclasses import dataclass
from datetime import date
from typing import Any

from sqlalchemy.orm import Session

from app.analytics.analyses import AnalysisDraft
from app.analytics.config import AnalyticsParams, TenantConfig, sha256_json
from app.db.models import AnalysisResult, Decision
from app.repositories import analysis as analysis_repo


def jsonable(value: Any) -> Any:
    """Round-trip through JSON so what is stored (and compared) is exactly what the database returns."""
    return json.loads(json.dumps(value, default=str, allow_nan=False))


def identity_parts(decision_id: str | uuid.UUID, draft: AnalysisDraft) -> tuple[str, str, str]:
    """(analysis_params_hash, slot, analysis_identity)."""
    params_hash = sha256_json(draft.identity_params)
    slot = "|".join([str(decision_id), draft.analysis_type, draft.metric_id or "", draft.key])
    identity = hashlib.sha256(f"{slot}|{params_hash}".encode()).hexdigest()
    return params_hash, slot, identity


def source_fingerprint(draft: AnalysisDraft) -> str:
    """SHA-256 of the aggregated rows the analysis consumed (the data-source fingerprint)."""
    return sha256_json(jsonable(draft.rows))


@dataclass(frozen=True)
class Stored:
    row: AnalysisResult
    reused: bool


def persist(session: Session, decision: Decision, draft: AnalysisDraft, *, params: AnalyticsParams, tenant: TenantConfig,
            dq_status: str, dq_note: str, as_of: date, agent_run_id: uuid.UUID | None) -> Stored:
    params_hash, slot, identity = identity_parts(decision.id, draft)
    fingerprint = source_fingerprint(draft)
    limitations = " ".join(x for x in (draft.method_limitations, dq_note) if x)
    result = jsonable(draft.result)
    content = sha256_json({"result": result, "n": draft.n, "dq_status": dq_status, "limitations": limitations,
                           "query_text": draft.query_text, "source_fingerprint": fingerprint})
    existing = analysis_repo.latest_for_identity(session, decision.id, identity)
    if existing is not None and (existing.params or {}).get("content_sha256") == content:
        return Stored(existing, True)
    stored_params = jsonable({
        "slot": slot, "analysis_type": draft.analysis_type, "key": draft.key, "metric_id": draft.metric_id,
        "metric_name": draft.metric_name, "source_views": draft.source_views, "primary_source_view": draft.extra.get("primary_view"),
        "query": {"name": draft.extra.get("query_name"), "params": draft.extra.get("query_params", {})},
        "config": {"analytics_params_version": params.version, "analytics_params_hash": params.content_hash,
                   "tenant_config_version": tenant.version, "tenant_config_hash": tenant.content_hash},
        "identity_params": draft.identity_params, "as_of": as_of.isoformat(), "content_sha256": content,
    })
    row = analysis_repo.add_analysis(
        session, decision_id=decision.id, agent_run_id=agent_run_id, analysis_type=draft.analysis_type, params=stored_params,
        query_text=draft.query_text, result=result, n=draft.n, limitations=limitations, dq_status=dq_status,
        analysis_identity=identity, params_hash=params_hash, source_fingerprint=fingerprint, is_synthetic=decision.is_synthetic)
    return Stored(row, False)
