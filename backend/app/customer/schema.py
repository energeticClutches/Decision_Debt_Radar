"""Classification output schema (docs/day-5-implementation-brief.md section 5, step 2; test C1).

The model output must parse as {"classifications": [{"text_ref", "theme", "relevance"}]} where theme is in the taxonomy or null and
relevance is direct, adjacent or not_relevant. Any out-of-taxonomy theme, unknown or repeated text_ref, missing text_ref, extra
field or malformed JSON fails the whole batch (the model never chooses a stance, a sentiment or anything else: D5-01).
"""

from __future__ import annotations

import json
from collections.abc import Collection

RELEVANCE = ("direct", "adjacent", "not_relevant")


class ClassificationSchemaError(ValueError):
    """The classifier output is not valid for the batch. The whole batch fails."""


def parse_classifications(raw_text: str, *, themes: Collection[str], text_refs: Collection[str]) -> dict[str, tuple[str | None, str]]:
    """text_ref -> (theme or None, relevance). Raises ClassificationSchemaError."""
    try:
        data = json.loads(raw_text)
    except (ValueError, TypeError) as exc:
        raise ClassificationSchemaError(f"the output is not valid JSON: {exc}") from exc
    if not isinstance(data, dict) or set(data) != {"classifications"} or not isinstance(data["classifications"], list):
        raise ClassificationSchemaError('the output must be an object with exactly one key, "classifications" (a list)')
    allowed_refs, allowed_themes = set(text_refs), set(themes)
    out: dict[str, tuple[str | None, str]] = {}
    for i, item in enumerate(data["classifications"]):
        if not isinstance(item, dict) or set(item) != {"text_ref", "theme", "relevance"}:
            raise ClassificationSchemaError(f"item {i} must have exactly the keys text_ref, theme and relevance")
        ref, theme, relevance = item["text_ref"], item["theme"], item["relevance"]
        if not isinstance(ref, str) or ref not in allowed_refs:
            raise ClassificationSchemaError(f"item {i}: unknown text_ref {ref!r}")
        if ref in out:
            raise ClassificationSchemaError(f"item {i}: text_ref {ref!r} appears more than once")
        if theme is not None and (not isinstance(theme, str) or theme not in allowed_themes):
            raise ClassificationSchemaError(f"item {i}: theme {theme!r} is not in the taxonomy")
        if relevance not in RELEVANCE:
            raise ClassificationSchemaError(f"item {i}: relevance {relevance!r} must be one of {RELEVANCE}")
        out[ref] = (theme, relevance)
    missing = allowed_refs - set(out)
    if missing:
        raise ClassificationSchemaError(f"{len(missing)} text_ref value(s) have no classification")
    return out
