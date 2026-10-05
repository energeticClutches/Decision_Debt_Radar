"""Brief constants and markdown rendering (docs/day-5-implementation-brief.md section 8, T2; tests B1 to B4).

Two kinds of document, never mixed:
  * Validated Decision Brief  (kind decision_brief)            only after the decision is validated or decided
  * Gated Evidence Summary    (kind gated_evidence_summary)    only for an insufficient_evidence assessment, labelled on EVERY
                                                               rendering "Gated Evidence Summary: not a validated decision artifact"

Deterministic sections come from stored data. The LLM sections are copied verbatim from the validated synthesis, sentence by
sentence, each with the claims and evidence it resolves to. There is NO recommendation section and no recommendation text.
"""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any

KIND_DECISION_BRIEF = "decision_brief"
KIND_GATED_SUMMARY = "gated_evidence_summary"
KINDS = (KIND_DECISION_BRIEF, KIND_GATED_SUMMARY)

GATED_LABEL = "Gated Evidence Summary: not a validated decision artifact"       # exact text (T2)
DECISION_BRIEF_LABEL = "Validated Decision Brief"
NO_AUTOMATED_REVIEW_BANNER = "No automated adversarial review"
SYNTHETIC_BANNER = "Synthetic data: FitConnect is a fictional company."
POSITIONING = "DDI is an evidence-risk heuristic, not a measure of decision quality. The LLM never makes the decision and gives no advice on it."


def _cell(value: Any) -> str:
    if value is None:
        return "n/a"
    if isinstance(value, float):
        return f"{value:.4g}"
    return str(value).replace("|", "/").replace("\n", " ")


def _table(headers: list[str], rows: list[list[Any]]) -> list[str]:
    if not rows:
        return ["_none_", ""]
    out = ["| " + " | ".join(headers) + " |", "|" + "|".join("---" for _ in headers) + "|"]
    out += ["| " + " | ".join(_cell(c) for c in row) + " |" for row in rows]
    return out + [""]


def render_markdown(content: Mapping[str, Any]) -> str:
    """Markdown rendering of a brief's content. The label is the first line and the last line (every rendering carries it)."""
    kind = content["kind"]
    label = content["label"]
    lines: list[str] = [f"**{label}**", "", f"# {content['title']}", ""]
    for banner in content["banners"]:
        lines.append(f"> {banner}")
    lines.append("")
    h = content["header"]
    lines += ["## Header", "",
              f"- Decision: {h['decision']['title']} (hypothesis: {h['decision']['hypothesis']})",
              f"- Success metric: {h['decision']['success_metric']}; expected direction: {h['decision']['expected_direction']}",
              f"- Assessment: version {h['assessment']['version']}, as of {h['assessment']['as_of_date']}, state {h['assessment']['state']}"
              f", lifecycle stage {h['decision']['lifecycle_label']}",
              f"- Evidence fingerprint: {h['assessment']['evidence_fingerprint']}"]
    for name, v in sorted(h["versions"].items()):
        lines.append(f"- {name}: {_cell(v)}")
    lines.append("")

    panel = content["ddi_panel"]
    lines += ["## DDI panel", ""]
    if panel["state"] == "scored":
        lines += [f"- DDI {panel['ddi']} ({panel['band']}); evidence direction: {content['direction'].get('label')}",
                  f"- {panel['positioning']}", ""]
        lines += _table(["Dimension", "Score", "Contribution"], [[d["id"] + " " + str(d.get("name")), d.get("score"), d.get("display_contribution")]
                                                              for d in panel["dimensions"]])
        lines += _table(["Penalty", "Score", "Contribution"], [[p["id"] + " " + str(p.get("name")), p.get("score"), p.get("display_contribution")]
                                                             for p in panel["penalties"]])
    else:
        lines += [f"- {panel['insufficient_evidence_label']}: no DDI, band, dimension or penalty exists for this assessment.", ""]
    if content["gate_reasons"]:
        lines += ["## Gate reasons", ""]
        for r in content["gate_reasons"]:
            lines.append(f"- {r.get('code')}: {r.get('message')}")
        lines.append("")
    if kind == KIND_GATED_SUMMARY:
        lines += ["## Why this assessment is gated", ""]
        for r in content.get("blocking_reasons_explained", []):
            lines.append(f"- {r['code']}: {r['explanation']}")
        lines.append("")
        lines += ["## Next best evidence: ways to unblock scoring (this is not advice on the decision)", ""]
        for a in content.get("unblocking_actions", []):
            lines.append(f"- {a['description']} (resolves {a['blockers_resolved']} blocker(s), about {a['effort_days']} day(s))")
        if not content.get("unblocking_actions"):
            lines.append("_none_")
        lines.append("")

    lines += ["## Evidence", ""]
    lines += _table(["Id", "Type", "Stance", "Grade", "Tier", "Status", "n", "Effect", "Summary"],
                    [[e["id"][:8], e["evidence_type"], e["stance"], e["grade"], e["tier"], e["status"], e.get("n_sample"),
                      e.get("effect_size"), e["summary"]] for e in content["evidence_table"]])
    lines += ["## Data quality", ""]
    lines += _table(["Target", "Severity", "Status", "Finding"], [[d["target"], d["severity"], d["status"], d["finding"]] for d in content["dq"]])
    het = content["heterogeneity"]
    lines += ["## Heterogeneity", "", f"- flag: {_cell(het.get('flag'))}", ""]
    if kind == KIND_DECISION_BRIEF:
        lines += ["## Next best evidence: ways to gather more evidence (this is not advice on the decision)", ""]
        for a in content["nbe"]:
            lines.append(f"- {a['description']} (about {a['effort_days']} day(s))")
        if not content["nbe"]:
            lines.append("_none_")
        lines.append("")

    syn = content.get("synthesis")
    lines += ["## Evidence synthesis (LLM text, validated; every sentence cites claims)", ""]
    if syn is None:
        lines += ["_No succeeded synthesis exists for this assessment._", ""]
    else:
        lines += [f"Synthesis version {syn['version']} (model {syn['model']}; provenance {syn['provenance']}).", ""]
        for title, key in (("Summary", "summary"), ("Supporting", "supporting"), ("Contradicting", "contradicting"),
                           ("Uncertainty", "uncertainty")):
            lines += [f"### {title}", ""]
            sentences = content["llm_sections"][key]
            if not sentences:
                lines += ["_none_", ""]
                continue
            for s in sentences:
                lines.append(f"- {s['text']} (claims: {', '.join(r['local_id'] for r in s['claim_refs'])})")
            lines.append("")
        lines += ["### Claims", ""]
        lines += _table(["Claim", "Type", "Stance", "Confidence", "Feeds", "Evidence", "Text"],
                        [[c["local_id"], c["claim_type"], c["stance"], c["confidence"], c["conclusion_ref"],
                          ", ".join(e[:8] for e in c["evidence_ids"]), c["text"]] for c in content["claims"]])
        lines += ["### Uncertainties and gaps", ""]
        for u in content["uncertainties"]:
            lines.append(f"- Uncertainty: {u['text']}")
        for g in content["gaps"]:
            lines.append(f"- Gap ({g['gap_type']}): {g['text']}")
        lines.append("")
        lines += ["### Change-my-mind criteria", ""]
        lines += _table(["Criterion", "Status", "Evidence"], [[c["text"], c["status"], ", ".join(e[:8] for e in c["evidence_ids"])]
                                                              for c in content["criteria_assessment"]])
    lines += ["## Review", ""]
    rv = content["review"]
    if rv["agent_review"] is None:
        lines.append(f"- {NO_AUTOMATED_REVIEW_BANNER}.")
    else:
        a = rv["agent_review"]
        lines.append(f"- Agent review (model {a['model']}): verdict {a['verdict']} (derived by code from the findings)")
        for f in a["findings"]:
            lines.append(f"  - {f['severity']} {f['category']} on {f['target_type']} {f.get('target_local_id') or f['target_id']}: {f['rationale']}")
    for hr in rv["human_reviews"]:
        lines.append(f"- Human review: {hr['verdict']}{' - ' + hr['human_response'] if hr.get('human_response') else ''}")
    lines.append("")
    rec = content.get("decision_record")
    if rec:
        lines += ["## Decision record (human)", "", f"- {rec['outcome']}: {rec['rationale']}", ""]
    lines += ["## Traceability appendix", ""]
    lines += _table(["Claim", "Type", "Stance", "Evidence", "Source (tier)", "Analysis", "Feeds"],
                    [[t.get("local_id") or (t["claim_text"] or "")[:60], t.get("claim_type"), t.get("stance"),
                      (t.get("evidence_id") or "")[:8], f"{t.get('source_name')} ({t.get('reliability_tier')})" if t.get("source_name") else None,
                      t.get("analysis_type"), t.get("conclusion_ref")] for t in content["traceability"]])
    lines += [f"_{SYNTHETIC_BANNER}_", f"_{POSITIONING}_", "", f"**{label}**"]
    return "\n".join(lines) + "\n"


__all__ = ["DECISION_BRIEF_LABEL", "GATED_LABEL", "KINDS", "KIND_DECISION_BRIEF", "KIND_GATED_SUMMARY", "NO_AUTOMATED_REVIEW_BANNER",
           "POSITIONING", "SYNTHETIC_BANNER", "render_markdown"]
