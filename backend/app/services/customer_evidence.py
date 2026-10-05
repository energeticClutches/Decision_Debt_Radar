"""Stage 3 customer evidence and its human approval (docs/day-5-implementation-brief.md sections 5 and 9).

    candidates   feedback of the analysis window read from the allow-listed feedback view through the SQL guard (never the
                 evaluation ground-truth table)
    classify     one LLM call per batch of DISTINCT texts that miss the cache (text_sha256 + taxonomy + prompt version + model);
                 theme and relevance only (D5-01). The output is validated against the closed taxonomy
    aggregate    deterministic counts per theme (app.customer.aggregate)
    propose      one `proposed` evidence item per (decision, theme) with enough relevant mentions, stance from the human-authored
                 theme map (D5-03), grade C or D (D5-06), tier from the feedback data source
    approve      a human approves or rejects the (decision, theme) item (T1). Only `active` items enter the DDI (D5-02)

Customer evidence is NOT materialised from an analysis_results row (there is none): its chain is evidence -> customer_insights
(counts, quotes) -> llm_classifications (one immutable row per feedback item, with the agent run) -> the feedback view.
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from typing import Any

from sqlalchemy import func

from app.analytics import queries as Q
from app.analytics.config import Taxonomy
from app.analytics.executor import ReadOnlyExecutor
from app.core.params import get_analytics_params, get_tenant_config
from app.customer.aggregate import ClassifiedRow, ThemeAggregate, aggregate, evidence_identity
from app.customer.schema import ClassificationSchemaError, parse_classifications
from app.db.models import AgentRun, Decision, Evidence, LlmClassification
from app.domain import permissions as perm
from app.domain.canvas import validate_evidence
from app.domain.errors import InvalidInput, NotFound, StateConflict
from app.domain.permissions import Actor
from app.llm import sanitize
from app.llm.builders import build_request, default_models
from app.llm.client import sha256_text
from app.llm.prompts import load_prompt
from app.llm.runs import call_llm, mark_run_failed
from app.repositories import audit as audit_repo
from app.repositories import customer as customer_repo
from app.repositories import decisions as decisions_repo
from app.repositories import evidence as evidence_repo
from app.repositories.users import parse_uuid
from app.services.base import ServiceContext, unit_of_work
from app.services.lifecycle import LifecycleHelpers

APPROVAL_ACTIONS = ("approve", "reject")


@dataclass(frozen=True)
class Candidate:
    feedback_id: int
    text: str
    text_sha256: str
    created_on: Any
    source: str
    segment: str | None


def summary_text(agg: ThemeAggregate, taxonomy: Taxonomy) -> str:
    """Deterministic evidence summary (no LLM text)."""
    sources = ", ".join(agg.source_types)
    return (f"Customer feedback theme '{agg.theme}' ({agg.stance}): {agg.mentions} relevant mentions from {len(agg.source_types)} "
            f"source type(s) ({sources}), {agg.first_mention.isoformat()} to {agg.last_mention.isoformat()}; {agg.direct} of them "
            f"direct ({agg.relevance_observed:.1%}, observed relevance, not used by DDI v0.1). The theme was assigned by an LLM from the "
            f"closed taxonomy {taxonomy.taxonomy_version}; the stance comes from the human-authored theme map. Self-reported "
            f"voice of the customer, not behavior. Synthetic data.")


class CustomerEvidenceService(LifecycleHelpers):
    def __init__(self, ctx: ServiceContext, *, executor: ReadOnlyExecutor | None = None):
        super().__init__(ctx)
        self.params = ctx.analytics_params or get_analytics_params()
        self.tenant = ctx.tenant or get_tenant_config()
        self._executor = executor or ctx.executor

    @property
    def executor(self) -> ReadOnlyExecutor:
        if self._executor is None:
            self._executor = ReadOnlyExecutor(max_rows=self.params.max_rows, statement_timeout=self.params.statement_timeout)
        return self._executor

    # ================================================================ Stage 3
    def run_stage(self, decision: Decision, run: AgentRun, *, client) -> tuple[dict, str]:
        """Called inside the pipeline stage transaction. Returns (output, status). An LLM failure is a `partial` stage with the
        reason (no evidence is created from an incomplete classification); it never raises, so the deterministic assessment still runs."""
        taxonomy = self.tenant.customer_taxonomy(decision.scenario_key)
        if taxonomy is None:
            return {"outcome": "no_taxonomy", "reason": "the tenant configuration defines no customer taxonomy for this decision"}, "succeeded"
        cust, llm = self.params.customer, self.params.llm
        models = dict(self.ctx.llm_models or default_models())
        model = models["classify"]
        prompt = load_prompt("classify", self.ctx.prompt_version)
        spec = self.tenant.customer_feedback()
        metric = decisions_repo.get_metric(self.session, decision.success_metric_id)
        seg_col = self.tenant.segment_key(metric.name) if metric is not None else None
        as_of = self.clock.today()
        window_end = datetime(as_of.year, as_of.month, as_of.day, tzinfo=UTC) + timedelta(days=1)
        raw_rows = self.executor.run(Q.feedback_candidates_query(spec, seg_col, self.params.max_rows), {"window_end": window_end})
        candidates = [Candidate(feedback_id=int(r["feedback_id"]), text=str(r["body"]), text_sha256=sha256_text(str(r["body"])),
                                created_on=r["created_at"].astimezone(UTC).date(), source=str(r["source"]),
                                segment=None if r["segment"] is None else str(r["segment"])) for r in raw_rows]
        distinct = {c.text_sha256: c.text for c in candidates}
        taxonomy_id = taxonomy.taxonomy_id
        cache = customer_repo.cached_classifications(self.session, sorted(distinct), taxonomy_id, prompt.version, model)
        results: dict[str, tuple[str | None, str, uuid.UUID]] = {h: (c.theme, c.relevance, c.agent_run_id) for h, c in cache.items()}
        misses = sorted(set(distinct) - set(results))
        out: dict[str, Any] = {"outcome": "completed", "taxonomy_version": taxonomy.taxonomy_version, "taxonomy_id": taxonomy_id,
                               "prompt_version": prompt.version, "model": model, "window_end": window_end.isoformat(),
                               "candidates": len(candidates), "distinct_texts": len(distinct), "cache_hits": len(cache),
                               "llm_calls": 0}
        failure = self._classify_misses(decision, client, taxonomy, prompt, model, misses, distinct, results, out, llm)
        inserted = self._store_classifications(decision, candidates, results, taxonomy_id, prompt, model)
        out["classifications_inserted"] = inserted
        if failure is not None:
            out.update({"outcome": "llm_failed", "error_class": failure[0], "error": failure[1],
                        "note": "classification is incomplete: no customer evidence was proposed. The deterministic assessment is unchanged."})
            out["pending_approvals"] = self._pending(decision)
            return out, "partial"
        rows = [ClassifiedRow(feedback_id=c.feedback_id, text_sha256=c.text_sha256, text=c.text, created_on=c.created_on, source=c.source,
                              segment=c.segment, theme=results[c.text_sha256][0], relevance=results[c.text_sha256][1]) for c in candidates]
        agg = aggregate(rows, taxonomy, min_theme_mentions=int(cust["min_theme_mentions"]),
                        grade_c_min_mentions=int(cust["grade_c_min_mentions"]),
                        grade_c_min_source_types=int(cust["grade_c_min_source_types"]),
                        sample_quotes_per_insight=int(cust["sample_quotes_per_insight"]))
        out["counts"] = dict(agg.counts)
        out["gaps"] = [g.as_dict() for g in agg.gaps]
        out["themes"], superseded_active = [], False
        for item in agg.themes:
            action, ev_id, flags = self._propose(decision, run, taxonomy, prompt, model, item)
            out["themes"].append({**item.as_dict(), "action": action, "evidence_id": ev_id, **flags})
            superseded_active = superseded_active or flags.get("superseded_active", False)
        if superseded_active:
            out["marked_stale"] = self.mark_stale_system(decision, "approved customer evidence was superseded by a new identity")
        out["pending_approvals"] = self._pending(decision)
        return out, "succeeded"

    # ---- classification
    def _classify_misses(self, decision, client, taxonomy, prompt, model, misses, distinct, results, out, llm) -> tuple[str, str] | None:
        size = int(llm["classification_batch_size"])
        theme_defs = [{"theme": t.theme, "description": t.description} for t in taxonomy.themes]
        for start in range(0, len(misses), size):
            chunk = misses[start:start + size]
            refs = {f"t{i + 1}": h for i, h in enumerate(chunk)}
            input_obj = {"task": "classify", "taxonomy": {"taxonomy_version": taxonomy.taxonomy_id, "themes": theme_defs},
                         "texts": [{"text_ref": ref, "text": sanitize.wrap(distinct[h])} for ref, h in refs.items()]}
            request = build_request(purpose="classify", prompt=prompt, input_obj=input_obj, model=model, llm_params=llm,
                                    meta={"scenario_key": decision.scenario_key})
            call = call_llm(self.session, client, request, decision_id=decision.id, assessment_id=None, stage="customer",
                            agent_name="evidence_synthesis", is_synthetic=decision.is_synthetic)
            out["llm_calls"] += 1
            if not call.ok:
                return call.error.error_class, str(call.error)[:300]
            try:
                parsed = parse_classifications(call.response.text, themes=taxonomy.theme_names, text_refs=list(refs))
            except ClassificationSchemaError as exc:
                mark_run_failed(self.session, call.run, "schema_error", str(exc))
                return "schema_error", str(exc)[:300]
            for ref, (theme, relevance) in parsed.items():
                results[refs[ref]] = (theme, relevance, call.run.id)
        return None

    def _store_classifications(self, decision, candidates, results, taxonomy_id, prompt, model) -> int:
        have = customer_repo.existing_feedback_ids(self.session, decision.id, taxonomy_id, prompt.version, model)
        new = [LlmClassification(decision_id=decision.id, feedback_id=c.feedback_id, text_sha256=c.text_sha256,
                                 taxonomy_version=taxonomy_id, theme=results[c.text_sha256][0], relevance=results[c.text_sha256][1],
                                 prompt_version=prompt.version, prompt_sha256=prompt.sha256, model=model,
                                 agent_run_id=results[c.text_sha256][2], is_synthetic=decision.is_synthetic)
               for c in candidates if c.text_sha256 in results and c.feedback_id not in have]
        return customer_repo.add_classifications(self.session, new)

    # ---- proposal
    def _propose(self, decision: Decision, run: AgentRun, taxonomy: Taxonomy, prompt, model: str, item: ThemeAggregate
                 ) -> tuple[str, str | None, dict]:
        identity = evidence_identity(str(decision.id), item.theme, taxonomy.taxonomy_id, prompt.version, model)
        existing = customer_repo.evidence_by_identity(self.session, decision.id, identity)
        if any(e.status == "rejected" for e in existing):
            return "rejected_not_reproposed", str(next(e for e in existing if e.status == "rejected").id), {}
        live = [e for e in existing if e.status in ("active", "proposed")]
        if live:
            return "unchanged", str(live[0].id), {"status": live[0].status}
        spec = self.tenant.customer_feedback()
        source = evidence_repo.evidence_source_by_ref(self.session, decision.org_id, str(spec["data_source_ref"]))
        if source is None:
            raise InvalidInput(f"No evidence source is registered for {spec['data_source_ref']}.", detail={"ref": spec["data_source_ref"]})
        insight = customer_repo.add_insight(
            self.session, org_id=decision.org_id, data_source_id=source.data_source_id, decision_id=decision.id, theme=item.theme,
            sentiment=item.sentiment, segment=None, quote_count=item.mentions, sample_quotes=list(item.sample_quotes),
            is_synthetic=decision.is_synthetic, relevance_observed=round(item.relevance_observed, 6),
            source_types=list(item.source_types), first_mention_date=item.first_mention, last_mention_date=item.last_mention,
            taxonomy_version=taxonomy.taxonomy_id, segment_counts=dict(item.segment_counts))
        fields = dict(evidence_type="customer", summary=summary_text(item, taxonomy), stance=item.stance, strength_grade=item.grade,
                      observed_start=item.first_mention, observed_end=item.last_mention, n_sample=item.mentions, effect_size=None,
                      ci_low=None, ci_high=None)
        validate_evidence(fields)
        ev = evidence_repo.add_evidence(
            self.session, decision_id=decision.id, evidence_source_id=source.id, analysis_id=None, metric_id=None, experiment_id=None,
            insight_id=insight.id, created_by="agent", agent_run_id=run.id, is_synthetic=decision.is_synthetic, status="proposed",
            analysis_identity=identity, source_fingerprint=item.fingerprint, **fields)
        audit_repo.add_audit(self.session, org_id=decision.org_id, actor_id=None, actor_type="system", action="evidence.proposed",
                             entity_type="evidence", entity_id=ev.id, decision_id=decision.id, before=None,
                             after={"theme": item.theme, "stance": ev.stance, "strength_grade": ev.strength_grade, "mentions": item.mentions,
                                    "taxonomy_id": taxonomy.taxonomy_id, "status": "proposed", "evidence_type": "customer"},
                             is_synthetic=decision.is_synthetic)
        flags: dict[str, Any] = {}
        for old in customer_repo.live_items_for_theme(self.session, decision.id, item.theme, except_identity=identity):
            was_active = old.status == "active"
            old.status = "superseded"
            old.superseded_by = ev.id
            old.superseded_at = func.clock_timestamp()
            self.session.flush()
            self.session.refresh(old)
            audit_repo.add_audit(self.session, org_id=decision.org_id, actor_id=None, actor_type="system", action="evidence.superseded",
                                 entity_type="evidence", entity_id=old.id, decision_id=decision.id,
                                 before={"status": "active" if was_active else "proposed"},
                                 after={"status": "superseded", "superseded_by": str(ev.id),
                                        "reason": "taxonomy, prompt or model changed (new identity)"},
                                 is_synthetic=decision.is_synthetic)
            flags["superseded_active"] = flags.get("superseded_active", False) or was_active
            flags.setdefault("superseded", []).append(str(old.id))
        return "proposed", str(ev.id), flags

    def _pending(self, decision: Decision) -> list[dict]:
        return [{"evidence_id": str(e.id), "theme": i.theme if i else None, "stance": e.stance, "strength_grade": e.strength_grade,
                 "mentions": e.n_sample, "status": e.status}
                for e, i in customer_repo.customer_items(self.session, decision.id) if e.status == "proposed"]

    def pending_approvals(self, decision: Decision) -> list[dict]:
        return self._pending(decision)

    # ================================================================ read
    def list(self, actor: Actor, decision_id) -> dict:
        decision = self.decision_or_404(actor, decision_id)
        items = []
        taxonomies: list[str] = []
        for ev, insight in customer_repo.customer_items(self.session, decision.id):
            tax_id = insight.taxonomy_version if insight else None
            if tax_id and tax_id not in taxonomies:
                taxonomies.append(tax_id)
            items.append({"evidence": ev, "insight": insight, "classification_counts":
                          customer_repo.classification_counts(self.session, decision.id, tax_id) if tax_id else None})
        counts = [customer_repo.classification_counts(self.session, decision.id, t) for t in customer_repo.classification_taxonomies(self.session, decision.id)]
        return {"decision": decision, "items": items, "classification_counts": counts,
                "pending_approvals": sum(1 for it in items if it["evidence"].status == "proposed")}

    # ================================================================ approval (T1)
    def set_approval(self, actor: Actor, evidence_id, action: str, note: str | None) -> Evidence:
        perm.authorize_role(actor, perm.APPROVE_EVIDENCE)
        if action not in APPROVAL_ACTIONS:
            raise InvalidInput(f"action must be one of {APPROVAL_ACTIONS}.")
        with unit_of_work(self.session):
            eid = parse_uuid(evidence_id)
            ev = evidence_repo.get_evidence(self.session, eid) if eid else None
            if ev is None:
                raise NotFound("Evidence item not found.")
            decision = self.decision_or_404(actor, ev.decision_id, lock=True)
            if decision.lifecycle_stage == "decided":
                raise StateConflict("The decision is decided: evidence can no longer be approved or rejected.")
            self.session.refresh(ev)
            if ev.status != "proposed":
                raise StateConflict(f"Only a proposed evidence item can be approved or rejected (this item is '{ev.status}').",
                                    detail={"status": ev.status})
            before = {"status": ev.status}
            ev.status = "active" if action == "approve" else "rejected"
            ev.approved_by = uuid.UUID(actor.id)
            ev.approved_at = self.clock.now()
            ev.approval_note = (note or "").strip() or None
            self.session.flush()
            self.session.refresh(ev)
            self.audit(actor, "evidence.approved" if action == "approve" else "evidence.rejected", "evidence", ev.id, decision,
                       before=before, after={"status": ev.status, "approval_note": ev.approval_note, "evidence_type": ev.evidence_type,
                                             "stance": ev.stance, "strength_grade": ev.strength_grade})
            self.mark_stale_if_needed(actor, decision, f"customer evidence {ev.status} after the assessment")
            return ev


__all__ = ["CustomerEvidenceService", "Candidate", "summary_text", "APPROVAL_ACTIONS"]
