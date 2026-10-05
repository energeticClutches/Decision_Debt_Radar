"""Deterministic aggregation of classified feedback into one customer insight per (decision, theme), and the grade (D5-04 to D5-06).

Pure functions: no database, no clock, no LLM. The same classified rows always give the same aggregates.

  * relevant mention  = a feedback row whose classification has a theme and a relevance other than not_relevant
  * a theme with relevant mentions >= min_theme_mentions becomes one proposed evidence item; a theme below it is reported as a gap
  * relevance_observed = the share of `direct` among the theme's relevant mentions (stored and displayed; NOT used by DDI v0.1)
  * sample quotes = distinct texts in ascending text_sha256 order (deterministic), at most `sample_quotes_per_insight`
  * grade = C if mentions >= grade_c_min_mentions and at least grade_c_min_source_types source types, otherwise D. Never A or B
  * identity = sha256(decision | theme | taxonomy_version | prompt_version | model)
"""

from __future__ import annotations

import hashlib
from collections import Counter
from collections.abc import Iterable, Mapping
from dataclasses import dataclass, field
from datetime import date

from app.analytics.config import Taxonomy, sha256_json

SENTIMENT_FOR_STANCE = {"supports": "positive", "contradicts": "negative", "neutral": "neutral"}


@dataclass(frozen=True)
class ClassifiedRow:
    feedback_id: int
    text_sha256: str
    text: str
    created_on: date
    source: str
    segment: str | None
    theme: str | None
    relevance: str


@dataclass(frozen=True)
class ThemeAggregate:
    theme: str
    stance: str
    sentiment: str
    mentions: int
    direct: int
    relevance_observed: float
    source_counts: Mapping[str, int]
    source_types: tuple[str, ...]
    first_mention: date
    last_mention: date
    segment_counts: Mapping[str, int]
    sample_quotes: tuple[Mapping[str, object], ...]
    grade: str
    fingerprint: str

    def as_dict(self) -> dict:
        return {"theme": self.theme, "stance": self.stance, "mentions": self.mentions, "direct": self.direct,
                "relevance_observed": round(self.relevance_observed, 6), "source_counts": dict(self.source_counts),
                "source_types": list(self.source_types), "first_mention": self.first_mention.isoformat(),
                "last_mention": self.last_mention.isoformat(), "segment_counts": dict(self.segment_counts), "grade": self.grade}


@dataclass(frozen=True)
class Gap:
    theme: str
    mentions: int
    min_theme_mentions: int

    def as_dict(self) -> dict:
        return {"gap_type": "customer_theme_below_threshold", "theme": self.theme, "relevant_mentions": self.mentions,
                "min_theme_mentions": self.min_theme_mentions}


@dataclass(frozen=True)
class AggregationResult:
    themes: tuple[ThemeAggregate, ...] = ()
    gaps: tuple[Gap, ...] = ()
    counts: Mapping[str, int] = field(default_factory=dict)       # classified rows, relevant rows, per-theme relevant mentions


def customer_grade(mentions: int, source_types: int, *, grade_c_min_mentions: int, grade_c_min_source_types: int) -> str:
    """Deterministic grade (D5-06): C or D only. Never A or B."""
    return "C" if mentions >= grade_c_min_mentions and source_types >= grade_c_min_source_types else "D"


def evidence_identity(decision_id: str, theme: str, taxonomy_id: str, prompt_version: str, model: str) -> str:
    return hashlib.sha256("|".join([str(decision_id), theme, taxonomy_id, prompt_version, model]).encode("utf-8")).hexdigest()


def aggregate(rows: Iterable[ClassifiedRow], taxonomy: Taxonomy, *, min_theme_mentions: int, grade_c_min_mentions: int,
              grade_c_min_source_types: int, sample_quotes_per_insight: int) -> AggregationResult:
    rows = list(rows)
    results: list[ThemeAggregate] = []
    gaps: list[Gap] = []
    per_theme_counts: dict[str, int] = {}
    for tt in taxonomy.themes:                                    # taxonomy order, so the output is deterministic
        mine = sorted((r for r in rows if r.theme == tt.theme and r.relevance != "not_relevant"), key=lambda r: r.feedback_id)
        per_theme_counts[tt.theme] = len(mine)
        if len(mine) < min_theme_mentions:
            gaps.append(Gap(tt.theme, len(mine), min_theme_mentions))
            continue
        sources = Counter(r.source for r in mine)
        direct = sum(1 for r in mine if r.relevance == "direct")
        segments = Counter(r.segment if r.segment is not None else "unknown" for r in mine)
        by_text: dict[str, list[ClassifiedRow]] = {}
        for r in mine:
            by_text.setdefault(r.text_sha256, []).append(r)
        quotes = tuple({"text": by_text[h][0].text, "text_sha256": h, "mentions": len(by_text[h]),
                        "sources": sorted({x.source for x in by_text[h]})}
                       for h in sorted(by_text)[:sample_quotes_per_insight])
        source_types = tuple(sorted(sources))
        first, last = min(r.created_on for r in mine), max(r.created_on for r in mine)
        fingerprint = sha256_json({"theme": tt.theme, "mentions": len(mine), "direct": direct, "sources": dict(sorted(sources.items())),
                                   "first": first.isoformat(), "last": last.isoformat(), "segments": dict(sorted(segments.items()))})
        results.append(ThemeAggregate(
            theme=tt.theme, stance=tt.stance, sentiment=SENTIMENT_FOR_STANCE[tt.stance], mentions=len(mine), direct=direct,
            relevance_observed=direct / len(mine), source_counts=dict(sorted(sources.items())), source_types=source_types,
            first_mention=first, last_mention=last, segment_counts=dict(sorted(segments.items())), sample_quotes=quotes,
            grade=customer_grade(len(mine), len(source_types), grade_c_min_mentions=grade_c_min_mentions,
                                 grade_c_min_source_types=grade_c_min_source_types),
            fingerprint=fingerprint))
    counts = {"classified_rows": len(rows), "relevant_rows": sum(per_theme_counts.values()), **{f"theme:{k}": v for k, v in per_theme_counts.items()}}
    return AggregationResult(tuple(results), tuple(gaps), counts)
