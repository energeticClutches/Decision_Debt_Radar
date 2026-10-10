"""The seeded-flaw (mutation) suite for the code layers: validators and deterministic critic checks.

Each flaw of tests/evals/mutations.yaml is seeded into a VALID synthesis built from the real input payload of a scenario (the demo path
after the customer evidence is approved). The suite measures what the CODE catches. It does not measure a model: reviewer recall and
false flags are NOT EVIDENCED (no live model; replay fixtures are hand-authored).

Clean controls are valid syntheses for the four scenarios; a flag on a clean control is a false flag of the code layers.
"""

from __future__ import annotations

import copy
import json
import uuid
from pathlib import Path
from typing import Any

import yaml

from app.synthesis import validators as v
from app.synthesis.review import code_findings

MUTATIONS_PATH = Path(__file__).resolve().parent / "mutations.yaml"
SCENARIOS = ("ai_coach", "community", "onboarding", "pricing")
RESULTS_PATH = Path(__file__).resolve().parents[2] / "analytics" / "eval" / "mutation_results.json"


def load_mutations() -> list[dict]:
    data = yaml.safe_load(MUTATIONS_PATH.read_text(encoding="utf-8"))
    assert data["synthetic"] is True
    return data["mutations"]


# ------------------------------------------------------------------ building blocks
def validation_context(payload: dict, design_rank: dict) -> v.ValidationContext:
    return v.ValidationContext(evidence={e["id"]: e for e in payload["evidence"]}, assessment=payload["assessment"],
                               assessment_state=payload["assessment"]["state"], criteria_count=len(payload["decision"]["criteria"]),
                               design_rank=dict(design_rank))


def clean_output(payload: dict) -> dict:
    """A VALID synthesis for the payload (one typed, staged claim per evidence item). When an open critical data-quality finding exists the
    synthesis says so in its gaps (an honest synthesis; without it the deterministic critic correctly flags dq_issue_ignored)."""
    from day5_support import synthesis_output_for
    out = synthesis_output_for(payload)
    if any(d["severity"] == "critical" and d["status"] == "open" for d in payload["dq_findings"]):
        out["gaps"] = list(out["gaps"]) + [{"text": "An open critical data quality issue blocks the success metric.", "gap_type": "other"}]
    return out


def _claim(local_id, text, ctype, stance, ids, ref, confidence="low") -> dict:
    return {"local_id": local_id, "text": text, "claim_type": ctype, "stance": stance, "confidence": confidence,
            "evidence_ids": list(ids), "conclusion_ref": ref}


def _first(payload, pred):
    return next((e for e in payload["evidence"] if pred(e)), None)


def _with_claim(base: dict, claim: dict) -> dict:
    out = copy.deepcopy(base)
    out["claims"].append(claim)
    return out


def _any_item(payload):
    return payload["evidence"][0]


# ------------------------------------------------------------------ the operations (closed list)
def op_no_evidence_ids(payload, base, others):
    return _with_claim(base, _claim("m1", "Retention improved after the launch.", "descriptive", "neutral", [], "D1"))


def op_unknown_id(payload, base, others):
    return _with_claim(base, _claim("m1", "A separate study shows the same.", "descriptive", "neutral", [str(uuid.uuid4())], "D1"))


def op_foreign_id(payload, base, others):
    foreign = next((p for name, p in others.items() if p is not payload and p["evidence"]), None)
    if foreign is None:
        return None
    fid = foreign["evidence"][0]["id"]
    return _with_claim(base, _claim("m1", "A related decision shows the same.", "descriptive", "neutral", [fid], "D1"))


def op_customer_claim_cites_behavioral(payload, base, others):
    item = _first(payload, lambda e: e["evidence_type"] == "behavioral")
    if item is None:
        return None
    return _with_claim(base, _claim("m1", "Customers describe the feature positively.", "customer", item["stance"], [item["id"]], "D5"))


def op_d4_claim_cites_customer(payload, base, others):
    item = _first(payload, lambda e: e["evidence_type"] == "customer")
    if item is None:
        return None
    return _with_claim(base, _claim("m1", "The experiment shows a clear result.", "descriptive", "neutral", [item["id"]], "D4"))


def op_supports_claim_cites_contradicting(payload, base, others):
    for etype in ("customer", "behavioral", "experiment", "financial"):
        sup = _first(payload, lambda e: e["evidence_type"] == etype and e["stance"] == "supports")
        con = _first(payload, lambda e: e["evidence_type"] == etype and e["stance"] == "contradicts")
        if sup and con:
            ctype = {"customer": "customer", "behavioral": "associative", "experiment": "descriptive", "financial": "financial"}[etype]
            ref = {"customer": "D5", "behavioral": "D1", "experiment": "D1", "financial": "D7"}[etype]
            return _with_claim(base, _claim("m1", "The evidence of this type is supportive overall.", ctype, "supports", [sup["id"], con["id"]], ref))
    return None


def _numeric_claim(text):
    def op(payload, base, others):
        item = _any_item(payload)
        return _with_claim(base, _claim("m1", text, "descriptive", "neutral", [item["id"]], "D1"))
    return op


op_invent_ddi = _numeric_claim("The DDI is 87.65 for this decision.")
op_invent_percentage = _numeric_claim("Retention is 4.73% higher for these users.")
op_invent_effect = _numeric_claim("The effect size is 0.3917.")
op_invent_p_value = _numeric_claim("The difference is significant at p = 0.0137.")
op_invent_ci = _numeric_claim("The interval runs from -0.0731 to 0.4419.")
op_invent_sample_size = _numeric_claim("The comparison covers 99,991 users.")


def op_wrong_sign(payload, base, others):
    item = _first(payload, lambda e: e["evidence_type"] in ("behavioral", "experiment") and e.get("effect_size") not in (None, 0))
    if item is None:
        return None
    word = "decreased" if item["effect_size"] > 0 else "increased"          # the opposite of the stored sign
    text = f"The measured outcome {word} by {abs(item['effect_size']) * 100:.2f}%."
    return _with_claim(base, _claim("m1", text, "descriptive", "neutral", [item["id"]], "D1"))


def op_causal_from_behavioral(payload, base, others):
    item = _first(payload, lambda e: e["evidence_type"] == "behavioral" and e.get("effect_size") is not None)
    if item is None:
        return None
    return _with_claim(base, _claim("m1", "The feature caused the change in the outcome.", "causal", item["stance"], [item["id"]], "D6"))


def op_management_should(payload, base, others):
    item = _any_item(payload)
    return _with_claim(base, _claim("m1", "Management should invest in this feature.", "descriptive", "neutral", [item["id"]], "D1"))


def op_imperative(payload, base, others):
    item = _any_item(payload)
    return _with_claim(base, _claim("m1", "Approve the investment.", "descriptive", "neutral", [item["id"]], "D1"))


def op_sufficient_while_gated(payload, base, others):
    if payload["assessment"]["state"] == "scored":
        return None
    item = _any_item(payload)
    return _with_claim(base, _claim("m1", "The evidence is sufficient to support the redesign.", "descriptive", "neutral", [item["id"]], "D1"))


def op_ddi_while_gated(payload, base, others):
    if payload["assessment"]["state"] == "scored":
        return None
    item = _any_item(payload)
    return _with_claim(base, _claim("m1", "The DDI is 62 out of 100 for this decision.", "descriptive", "neutral", [item["id"]], "D1"))


def op_uncited_sentence(payload, base, others):
    out = copy.deepcopy(base)
    out["sections"]["summary"] = out["sections"]["summary"] + " Everything looks fine overall."
    return out


def op_omit_contradiction(payload, base, others):
    contradicting = {e["id"] for e in payload["evidence"] if e["stance"] == "contradicts"}
    if not contradicting:
        return None
    out = copy.deepcopy(base)
    out["claims"] = [c for c in out["claims"] if not set(c["evidence_ids"]) & contradicting]
    return out


def op_ignore_dq(payload, base, others):
    if not any(d["severity"] == "critical" and d["status"] == "open" for d in payload["dq_findings"]):
        return None
    out = copy.deepcopy(base)
    out["gaps"] = [g for g in out["gaps"] if "data quality" not in g["text"].lower()]
    return out


def op_high_confidence_weak(payload, base, others):
    weak = {e["id"] for e in payload["evidence"] if e.get("grade") in ("C", "D")}
    out = copy.deepcopy(base)
    changed = False
    for c in out["claims"]:
        if c["evidence_ids"] and set(c["evidence_ids"]) <= weak:
            c["confidence"] = "high"
            changed = True
    return out if changed else None


OPS = {name[3:]: fn for name, fn in globals().items() if name.startswith("op_")}


# ------------------------------------------------------------------ evaluation
def observed_tokens(output: dict, payload: dict, ctx: v.ValidationContext) -> dict[str, Any]:
    validated, report = v.validate_synthesis(output, ctx)
    rules = {row["rule"] for section in (report.dropped, report.reclassified, report.repaired, report.rejections, report.other_dropped)
             for row in section if row.get("rule")}
    critic = {f["category"] for f in code_findings(validated, payload)}
    # the critic runs on what survived validation (what the Reviewer is given), as in the product
    ids = set(ctx.evidence)
    pre_valid = sum(1 for c in output["claims"] if c["evidence_ids"] and set(c["evidence_ids"]) <= ids)
    post_valid = sum(1 for c in validated["claims"] if c["evidence_ids"] and set(c["evidence_ids"]) <= ids)
    return {"validator_rules": sorted(rules), "critic_categories": sorted(critic), "status": report.status,
            "claims_total": len(output["claims"]), "claims_valid_before_filter": pre_valid,
            "claims_surviving": len(validated["claims"]), "claims_valid_after_filter": post_valid}


def run_suite(payloads: dict[str, dict], design_rank: dict) -> dict:
    """payloads: scenario -> the real input payload. Returns the full results (JSON-safe)."""
    contexts = {k: validation_context(p, design_rank) for k, p in payloads.items()}
    controls, instances = [], []
    for name, payload in payloads.items():
        base = clean_output(payload)
        obs = observed_tokens(base, payload, contexts[name])
        flagged = bool(obs["validator_rules"] or obs["critic_categories"] or obs["status"] != "passed")
        controls.append({"scenario": name, **obs, "flagged": flagged})
    for mut in load_mutations():
        for name in mut["scenarios"]:
            payload = payloads[name]
            out = OPS[mut["op"]](payload, clean_output(payload), payloads)
            if out is None:
                instances.append({"id": mut["id"], "flaw": mut["flaw"], "scenario": name, "applicable": False, "caught": None})
                continue
            obs = observed_tokens(out, payload, contexts[name])
            catcher = mut["catcher"]
            want = catcher.get("rule") or catcher.get("category")
            fired = obs["validator_rules"] if catcher["layer"] == "validator" else obs["critic_categories"]
            instances.append({"id": mut["id"], "flaw": mut["flaw"], "scenario": name, "applicable": True, "layer": catcher["layer"],
                              "must_be_caught_by": want, "caught": want in fired, **obs,
                              "known_miss": mut.get("known_miss")})
    applicable = [i for i in instances if i["applicable"]]
    caught = [i for i in applicable if i["caught"]]
    return {
        "synthetic": True,
        "label": "Synthetic data. Code-layer seeded-flaw suite on syntheses built from real payloads; no model is involved. Reviewer "
                 "recall and false-flag rate are NOT EVIDENCED (no live model; replay fixtures are hand-authored).",
        "controls": controls, "instances": instances,
        "summary": {"flaw_types": len({i["id"] for i in applicable}), "instances": len(applicable), "caught": len(caught),
                    "recall": round(len(caught) / len(applicable), 4) if applicable else None,
                    "not_applicable": len(instances) - len(applicable),
                    "controls": len(controls), "controls_flagged": sum(1 for c in controls if c["flagged"]),
                    "false_flag_rate": round(sum(1 for c in controls if c["flagged"]) / len(controls), 4) if controls else None,
                    "citation_valid_before_filter": sum(i["claims_valid_before_filter"] for i in applicable) + sum(c["claims_valid_before_filter"] for c in controls),
                    "claims_total": sum(i["claims_total"] for i in applicable) + sum(c["claims_total"] for c in controls),
                    "citation_valid_after_filter": sum(i["claims_valid_after_filter"] for i in applicable) + sum(c["claims_valid_after_filter"] for c in controls),
                    "claims_surviving": sum(i["claims_surviving"] for i in applicable) + sum(c["claims_surviving"] for c in controls)},
    }


def write_results(results: dict, path: Path = RESULTS_PATH) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(results, indent=2, ensure_ascii=False) + "\n", encoding="utf-8", newline="\n")
