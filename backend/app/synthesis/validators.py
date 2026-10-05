"""Deterministic validators of an Evidence Synthesis (docs/day-5-implementation-brief.md section 6.2, tests V1, S2, E2).

Pure code: no database, no LLM, no clock. They run BEFORE any claim is stored. Rules, in the order they are applied to each claim:

  V-ID         every cited evidence id is in the supplied active set                                  -> drop the claim, log it
  V-SEM-TYPE   the claim type fits the cited evidence types (T3)                                      -> drop, or reclassify causal -> associative
  V-SEM-STANCE a `supports` claim cites a supporting item and no contradicting one, a `contradicts` claim the reverse -> drop, log it
  V-SEM-SCOPE  conclusion_ref (D1-D7, P1, P2, gate) is consistent with the cited types                -> drop, log it
  V-NUM        every number in the claim text appears, within rounding, in the CITED items or the DDI payload -> drop, log it
  V-REC        no recommendation or imperative phrasing in any field                                  -> the synthesis is rejected
  V-GATE       an insufficient assessment never reads as sufficient and never shows a DDI number       -> the synthesis is rejected
  V-REF        every [[local_id]] in a section names a surviving claim; a section sentence without one is removed -> repair, log it

More than 50% of the claims dropped, or no surviving claim, rejects the synthesis. The report is stored and given to the Reviewer.
A citation that exists in the input but does not support the claim (right id, wrong type, stance or scope) is caught by
V-SEM-TYPE, V-SEM-STANCE and V-SEM-SCOPE: the id check alone is not enough (T3).
"""

from __future__ import annotations

import re
from collections.abc import Iterable, Mapping, Sequence
from dataclasses import dataclass, field
from typing import Any

from app.synthesis.schema import CONCLUSION_REFS, SECTION_KEYS

# ---------------------------------------------------------------- recommendation and gate language
RECOMMENDATION_DENY = (
    "should approve", "should reject", "should proceed", "should launch", "should invest", "should not invest", "should defer",
    "should go ahead", "should fund", "should ship", "should cancel", "should raise", "should not proceed", "should not launch",
    "we recommend", "i recommend", "recommend that", "recommend approving", "recommend rejecting", "recommended action",
    "our recommendation", "the recommendation is", "we suggest", "i suggest", "go ahead", "go-ahead", "green light", "greenlight",
    "proceed with", "do not proceed", "don't proceed", "no-go", "go/no-go", "must approve", "must reject", "must launch",
    "reject the proposal", "approve the proposal", "advise to", "advise that", "advisable to", "it is advisable",
)
# an imperative that opens a sentence ("Approve the investment.", "Launch now.")
_IMPERATIVE_OPENERS = ("approve", "reject", "launch", "invest", "proceed", "cancel", "fund", "stop", "defer", "delay", "adopt", "ship",
                       "implement", "go ahead", "do not", "don't")
_RECOMMEND_WORD = re.compile(r"\brecommend(?:s|ed|ing|ation|ations)?\b", re.IGNORECASE)
_SHOULD_ACTION = re.compile(r"\b(?:should|must|ought to|needs? to)\s+(?:be\s+)?(?:approve[ds]?|reject(?:ed)?|launch(?:ed)?|invest(?:ed)?|"
                            r"proceed|cancel(?:led)?|fund(?:ed)?|ship(?:ped)?|adopt(?:ed)?|defer(?:red)?|roll(?:ed)? out|go ahead)\b", re.IGNORECASE)

_SUFFICIENT = re.compile(
    r"\bsufficient (?:evidence|data|support|basis)\b|\benough evidence\b|\bevidence is (?:strong|robust|solid|adequate|sufficient|"
    r"conclusive|complete)\b|\b(?:strong|robust|solid|conclusive|compelling|adequate) evidence\b|\bwell[- ]supported\b|"
    r"\bfully supported\b", re.IGNORECASE)
_NEGATION = ("no ", "not ", "without ", "lack", "never", "n't ", "insufficient", "little ", "limited ")


def says_sufficient(text: str) -> bool:
    """True if the text describes the evidence as sufficient (a negated phrase such as 'no strong evidence' does not count)."""
    for m in _SUFFICIENT.finditer(text):
        before = text[max(0, m.start() - 16):m.start()].lower()
        if not any(neg in before for neg in _NEGATION):
            return True
    return False


_DDI_NUMBER = re.compile(r"\bDDI\b[^.\n]{0,40}?\d|\bdecision debt\b[^.\n]{0,40}?\d|\b\d+(?:\.\d+)?\s*(?:/|out of)\s*100\b", re.IGNORECASE)
_DDI_BAND = re.compile(r"\b(?:low|moderate|high|critical)\b[ -](?:ddi|debt|band)|\bband (?:is |of )?(?:low|moderate|high|critical)\b", re.IGNORECASE)

# ---------------------------------------------------------------- numbers
_ISO_DATE = re.compile(r"\b\d{4}-\d{2}-\d{2}\b")
_LOCAL_REF = re.compile(r"\[\[[^\]]*\]\]")
_CODE_TOKEN = re.compile(r"\b[DPE][0-9]\b")
_NUMBER = re.compile(r"(?<![\w.])[-+]?\d[\d,]*(?:\.\d+)?%?")


@dataclass(frozen=True)
class ClaimNumber:
    value: float
    decimals: int
    percent: bool
    raw: str


def numbers_in(text: str) -> list[ClaimNumber]:
    """The numbers written in a text (dates, [[refs]] and code tokens such as D4 or P1 are ignored; 4-digit years are not numbers)."""
    cleaned = _CODE_TOKEN.sub(" ", _LOCAL_REF.sub(" ", _ISO_DATE.sub(" ", text)))
    out = []
    for m in _NUMBER.finditer(cleaned):
        raw = m.group(0)
        body = raw.rstrip("%").replace(",", "").lstrip("+-")
        if not body or body == ".":
            continue
        decimals = len(body.split(".")[1]) if "." in body else 0
        value = float(body)
        if decimals == 0 and not raw.endswith("%") and 1900 <= value <= 2100:
            continue
        out.append(ClaimNumber(value, decimals, raw.endswith("%"), raw))
    return out


def number_leaves(obj: Any, *, string_keys: Sequence[str] = ("summary", "finding", "explanation", "text")) -> list[float]:
    """Every numeric value in a nested structure (absolute values), plus the numbers written in the named text fields."""
    found: list[float] = []

    def walk(x: Any, key: str | None = None) -> None:
        if isinstance(x, bool) or x is None:
            return
        if isinstance(x, (int, float)):
            found.append(abs(float(x)))
        elif isinstance(x, str):
            if key in string_keys:
                found.extend(n.value for n in numbers_in(x))
        elif isinstance(x, Mapping):
            for k, v in x.items():
                walk(v, str(k))
        elif isinstance(x, (list, tuple)):
            for v in x:
                walk(v, key)
    walk(obj)
    return found


def number_matches(n: ClaimNumber, candidates: Iterable[float]) -> bool:
    """True if the claim number equals a candidate within rounding: at the claim's own number of decimal places, either as written
    or as a percentage of a stored fraction (0.2304 and 23.0%)."""
    tol = 0.5 * 10 ** (-n.decimals) + 1e-9
    for c in candidates:
        c = abs(c)
        if abs(c - n.value) <= tol or abs(c * 100 - n.value) <= tol:
            return True
    return False


# ---------------------------------------------------------------- context and report
@dataclass(frozen=True)
class ValidationContext:
    """Everything a validator needs, taken from the synthesis input (never from the model output)."""
    evidence: Mapping[str, Mapping[str, Any]]      # id -> evidence item of the input
    assessment: Mapping[str, Any]                  # the DDI result payload of the input
    assessment_state: str
    criteria_count: int
    design_rank: Mapping[str, int]                 # DDI design ranks (rct, holdout, pre_post, other)

    @property
    def insufficient(self) -> bool:
        return self.assessment_state != "scored"


@dataclass
class ValidatorReport:
    claims_total: int = 0
    dropped: list[dict] = field(default_factory=list)
    reclassified: list[dict] = field(default_factory=list)
    repaired: list[dict] = field(default_factory=list)
    rejections: list[dict] = field(default_factory=list)
    other_dropped: list[dict] = field(default_factory=list)          # uncertainties, criteria
    surviving: list[str] = field(default_factory=list)
    status: str = "passed"                                            # passed | rejected_by_validators

    @property
    def claims_dropped(self) -> int:
        return len(self.dropped)

    def as_dict(self) -> dict:
        return {"status": self.status, "claims_total": self.claims_total, "claims_dropped": self.claims_dropped,
                "claims_surviving": len(self.surviving), "dropped": self.dropped, "reclassified": self.reclassified,
                "repaired": self.repaired, "rejections": self.rejections, "other_dropped": self.other_dropped,
                "surviving": self.surviving}


# ---------------------------------------------------------------- claim rules (pure, one claim at a time)
def check_ids(claim: Mapping, ctx: ValidationContext) -> str | None:
    ids = claim["evidence_ids"]
    if not ids:
        return "the claim cites no evidence id"
    unknown = [i for i in ids if i not in ctx.evidence]
    if unknown:
        return f"cited evidence id(s) not in the supplied active evidence: {unknown}"
    return None


def _cited(claim: Mapping, ctx: ValidationContext) -> list[Mapping[str, Any]]:
    return [ctx.evidence[i] for i in claim["evidence_ids"] if i in ctx.evidence]


def _qualifying_experiment(item: Mapping[str, Any], ctx: ValidationContext) -> bool:
    """A causal claim needs an experiment of design rank at least `holdout` whose sample-ratio check passed (TM-6)."""
    if item.get("evidence_type") != "experiment":
        return False
    exp = item.get("experiment") or {}
    rank, need = ctx.design_rank.get(str(exp.get("design"))), ctx.design_rank.get("holdout")
    return rank is not None and need is not None and rank >= need and exp.get("srm_flag") is False


def check_type(claim: Mapping, ctx: ValidationContext) -> tuple[str | None, str | None]:
    """(reason to drop | None, new claim_type | None). Reclassification is causal -> associative only."""
    cited, ctype = _cited(claim, ctx), claim["claim_type"]
    types = {i.get("evidence_type") for i in cited}
    if ctype == "causal":
        if any(_qualifying_experiment(i, ctx) for i in cited):
            return None, None
        ctype = "associative"
        reclass = "associative"
    else:
        reclass = None
    if ctype == "customer" and "customer" not in types:
        return "a customer claim must cite at least one customer evidence item", None
    if ctype == "financial" and "financial" not in types:
        return "a financial claim must cite at least one financial evidence item", None
    if ctype == "associative" and not ({"behavioral", "experiment"} & types):
        return "an associative claim must cite behavioral or experiment evidence", None
    return None, reclass


def check_stance(claim: Mapping, ctx: ValidationContext) -> str | None:
    stances = [i.get("stance") for i in _cited(claim, ctx)]
    if claim["stance"] == "supports":
        if "supports" not in stances:
            return "a supports claim must cite at least one supporting evidence item"
        if "contradicts" in stances:
            return "a supports claim must not cite a contradicting evidence item (mixed evidence is a neutral claim)"
    if claim["stance"] == "contradicts":
        if "contradicts" not in stances:
            return "a contradicts claim must cite at least one contradicting evidence item"
        if "supports" in stances:
            return "a contradicts claim must not cite a supporting evidence item (mixed evidence is a neutral claim)"
    return None


def check_scope(claim: Mapping, ctx: ValidationContext) -> str | None:
    ref, cited = claim.get("conclusion_ref"), _cited(claim, ctx)
    if ref not in CONCLUSION_REFS:
        return f"conclusion_ref {ref!r} is not one of {list(CONCLUSION_REFS)}"
    types = {i.get("evidence_type") for i in cited}
    if ref == "D4" and "experiment" not in types:
        return "D4 (experimental strength) needs a cited experiment item"
    if ref == "D5" and "customer" not in types:
        return "D5 (customer evidence) needs a cited customer item"
    if ref == "D6" and not any(i.get("evidence_type") == "behavioral" and i.get("effect_size") is not None for i in cited):
        return "D6 (behavioral evidence) needs a cited behavioral item with an effect size"
    if ref == "D7" and "financial" not in types:
        return "D7 (financial evidence) needs a cited financial item"
    if ref == "P1" and not any(i.get("stance") == "contradicts" for i in cited):
        return "P1 (contradiction) needs a cited contradicting item"
    return None


def check_numbers(claim: Mapping, ctx: ValidationContext) -> str | None:
    nums = numbers_in(claim["text"])
    if not nums:
        return None
    candidates = number_leaves([dict(i) for i in _cited(claim, ctx)]) + number_leaves(ctx.assessment)
    bad = [n.raw for n in nums if not number_matches(n, candidates)]
    if bad:
        return f"number(s) {bad} do not appear in the cited evidence items or the DDI result"
    return None


# ---------------------------------------------------------------- text rules (whole synthesis)
def _texts(output: Mapping[str, Any]) -> list[tuple[str, str]]:
    out = [(f"claims.{c['local_id']}", c["text"]) for c in output["claims"]]
    out += [(f"uncertainties[{i}]", u["text"]) for i, u in enumerate(output["uncertainties"])]
    out += [(f"gaps[{i}]", f"{g['text']} {g['gap_type']}") for i, g in enumerate(output["gaps"])]
    out += [(f"sections.{k}", output["sections"][k]) for k in SECTION_KEYS]
    return out


def recommendation_hits(text: str) -> list[str]:
    low = " " + text.lower().replace("’", "'") + " "
    hits = [p for p in RECOMMENDATION_DENY if p in low]
    if _RECOMMEND_WORD.search(text) and "recommend" not in "".join(hits):
        hits.append("recommend*")
    if _SHOULD_ACTION.search(text):
        hits.append("should/must + action")
    for sentence in re.split(r"(?<=[.!?])\s+", text.strip()):
        s = re.sub(r"^[\s\-*•]+", "", sentence).lower()
        if any(s == w or s.startswith(w + " ") for w in _IMPERATIVE_OPENERS):
            hits.append(f"imperative: {sentence[:40]}")
    return hits


def check_recommendation(output: Mapping[str, Any]) -> list[dict]:
    """V-REC over every free-text field. Any hit rejects the synthesis."""
    found = []
    for where, text in _texts(output):
        hits = recommendation_hits(text)
        if hits:
            found.append({"rule": "V-REC", "where": where, "phrases": sorted(set(hits))})
    return found


def check_gate(output: Mapping[str, Any], ctx: ValidationContext) -> list[dict]:
    """V-GATE: for an insufficient assessment no text may call the evidence sufficient or present a DDI number or band."""
    if not ctx.insufficient:
        return []
    found = []
    for where, raw in _texts(output):
        text = _LOCAL_REF.sub(" ", raw)          # a [[c2]] reference is not a number
        problems = []
        if says_sufficient(text):
            problems.append("describes the evidence as sufficient")
        if _DDI_NUMBER.search(text) or _DDI_BAND.search(text):
            problems.append("presents a DDI number or band")
        if problems:
            found.append({"rule": "V-GATE", "where": where, "problems": problems})
    return found


# ---------------------------------------------------------------- sections (V-REF)
def split_sentences(text: str) -> list[str]:
    return [s for s in re.split(r"(?<=[.!?])\s+", text.strip()) if s.strip()]


def repair_sections(sections: Mapping[str, str], surviving: set[str], report: ValidatorReport) -> dict[str, str]:
    """V-REF. References to dropped or unknown claims are removed and noted. A sentence that no longer cites a surviving claim is
    removed and noted (every sentence of a brief must resolve to a claim, B4)."""
    out: dict[str, str] = {}
    for key in SECTION_KEYS:
        kept = []
        for sentence in split_sentences(sections.get(key, "")):
            refs = re.findall(r"\[\[([^\]]*)\]\]", sentence)
            bad = [r for r in refs if r not in surviving]
            for r in bad:
                report.repaired.append({"rule": "V-REF", "where": f"sections.{key}", "removed_ref": r,
                                        "reason": "refers to a claim that was dropped or does not exist"})
            cleaned = sentence
            for r in set(bad):
                cleaned = cleaned.replace(f"[[{r}]]", "")
            cleaned = re.sub(r"\s+([.,;:!?])", r"\1", re.sub(r"[ \t]{2,}", " ", cleaned)).strip()
            if any(r in surviving for r in refs):
                kept.append(cleaned)
            else:
                report.repaired.append({"rule": "V-REF", "where": f"sections.{key}", "removed_sentence": sentence[:120],
                                        "reason": "the sentence cites no surviving claim"})
        out[key] = " ".join(kept)
    return out


# ---------------------------------------------------------------- the whole synthesis
def validate_synthesis(output: Mapping[str, Any], ctx: ValidationContext) -> tuple[dict[str, Any], ValidatorReport]:
    """Apply every rule. Returns (the validated output: surviving claims and repaired sections, the report)."""
    report = ValidatorReport(claims_total=len(output["claims"]))
    surviving: list[dict] = []
    for claim in output["claims"]:
        claim = dict(claim)
        problem = check_ids(claim, ctx)
        rule = "V-ID"
        if problem is None:
            problem, reclass = check_type(claim, ctx)
            rule = "V-SEM-TYPE"
            if problem is None and reclass:
                report.reclassified.append({"rule": "V-SEM-TYPE", "local_id": claim["local_id"], "from": claim["claim_type"], "to": reclass,
                                            "reason": "a causal claim needs an experiment of design holdout or better with a passing SRM check (TM-6)"})
                claim["claim_type"] = reclass
        if problem is None:
            problem, rule = check_stance(claim, ctx), "V-SEM-STANCE"
        if problem is None:
            problem, rule = check_scope(claim, ctx), "V-SEM-SCOPE"
        if problem is None:
            problem, rule = check_numbers(claim, ctx), "V-NUM"
        if problem is not None:
            report.dropped.append({"rule": rule, "local_id": claim["local_id"], "reason": problem, "claim_text": claim["text"][:200],
                                   "evidence_ids": claim["evidence_ids"]})
            continue
        surviving.append(claim)
    report.surviving = [c["local_id"] for c in surviving]

    uncertainties = []
    for i, u in enumerate(output["uncertainties"]):
        unknown = [e for e in u["evidence_ids"] if e not in ctx.evidence]
        if unknown:
            report.other_dropped.append({"rule": "V-ID", "where": f"uncertainties[{i}]", "reason": f"unknown evidence id(s) {unknown}"})
        else:
            uncertainties.append(u)
    criteria = []
    for i, c in enumerate(output["criteria_assessment"]):
        unknown = [e for e in c["evidence_ids"] if e not in ctx.evidence]
        if unknown or not 0 <= c["criterion_index"] < ctx.criteria_count:
            report.other_dropped.append({"rule": "V-ID", "where": f"criteria_assessment[{i}]",
                                         "reason": f"unknown evidence id(s) {unknown}" if unknown else "criterion_index out of range"})
        else:
            criteria.append(c)

    # rejections on the text as the model wrote it (V-REC, V-GATE), before any repair
    report.rejections.extend(check_recommendation(output))
    report.rejections.extend(check_gate(output, ctx))
    if report.claims_total and report.claims_dropped / report.claims_total > 0.5:
        report.rejections.append({"rule": "V-DROP", "reason": f"{report.claims_dropped} of {report.claims_total} claims were dropped (more than 50%)"})
    if not surviving:
        report.rejections.append({"rule": "V-DROP", "reason": "no claim survived validation"})
    sections = repair_sections(output["sections"], {c["local_id"] for c in surviving}, report)
    validated = {"claims": surviving, "uncertainties": uncertainties, "gaps": list(output["gaps"]), "criteria_assessment": criteria,
                 "sections": sections}
    report.status = "rejected_by_validators" if report.rejections else "passed"
    return validated, report


__all__ = ["ClaimNumber", "RECOMMENDATION_DENY", "ValidationContext", "ValidatorReport", "check_gate", "check_ids", "check_numbers",
           "check_recommendation", "check_scope", "check_stance", "check_type", "number_leaves", "number_matches", "numbers_in",
           "recommendation_hits", "repair_sections", "says_sufficient", "split_sentences", "validate_synthesis"]
