"""Deterministic keyword-rule STUB classifier (test-only). It is NOT a model and its output is NOT model output.

Why it exists (docs/day-5-implementation-brief.md section 2, P2): no API key exists on Day 5 and a hand-written fixture for ~6,000
feedback texts is impractical. This stub implements the LlmClient protocol with plain keyword rules, so the whole customer-evidence
pipeline (batching, schema validation, cache, aggregation, proposal, approval) runs in CI without a network.

Honesty rules (hard constraints):
  * every response carries provenance "stub_not_model_output" and the model name "stub:keyword_rules_v1", so a stored agent_runs row
    or llm_classifications row never claims that a real model produced it
  * the rules are authored from the taxonomy DESCRIPTIONS in backend/config/orgs/fitconnect/analytics_config_v0.2.yaml (what a human
    would look for when reading each description). They were not derived from, and never read, the evaluation ground-truth labels:
    this module has no database access and no import of any app code except the LlmRequest/LlmResponse types
  * a text that mentions the product area without a clear cue gets theme null and relevance adjacent; anything else not_relevant

E1 measures this stub against the ground truth: it measures the PIPELINE and the stub, not any model. The synthetic feedback is
templated (a few dozen distinct sentences), so keyword rules do very well on it; that says nothing about real customer text.
"""

from __future__ import annotations

import html
import json
import re

from app.llm.client import PROVENANCE_STUB, LlmRequest, LlmResponse

MODEL = "stub:keyword_rules_v1"

# (topic keywords: the text is about the product area, ordered cue rules: the first matching rule wins)
RULES: dict[str, dict] = {
    # ---- AI Coach taxonomy
    "coach_generic_or_wrong": {"topic": "coach", "area": "coach",
        "cues": ["repeating", "repeat the same", "generic", "ignored my", "not impressed", "wrong advice", "irrelevant advice"]},
    "coach_indifferent": {"topic": "coach", "area": "coach",
        "cues": ["it is okay", "is fine but", "mostly follow my own", "not sure the coach", "tried the ai coach"]},
    "coach_helpful": {"topic": "coach", "area": "coach",
        "cues": ["keeps me on track", "adjusts my workouts", "daily tips", "easier to stick", "feels personal", "spot on", "really helpful"]},
    # ---- Community taxonomy
    "notifications_unwanted": {"topic": "challenge", "area": "community",
        "cues": ["notification", "reminders are pushy", "pinged", "pushy", "stress me out", "muted the app"]},
    "challenges_motivating": {"topic": "challenge", "area": "community",
        "cues": ["keep me motivated", "keeps me motivated", "love competing", "got me back into a routine", "motivated"]},
    "challenges_indifferent": {"topic": "challenge", "area": "community",
        "cues": ["not really for me", "i train alone", "challenges are fine"]},
    # ---- Onboarding taxonomy
    "setup_blocked": {"topic": "setup|onboarding|welcome flow|wizard|signed up", "area": "onboarding",
        "cues": ["stuck", "froze", "could not finish", "could not continue", "confusing", "gave up", "looping", "keeps looping",
                 "never got through", "crashed", "cannot complete onboarding"]},
    # ---- Pricing taxonomy
    "price_too_high": {"topic": "premium|price|pricey|subscription|expensive", "area": "pricing",
        "cues": ["too expensive", "will cancel", "hard to justify", "too pricey", "downgrading", "subscription cost", "price goes up"]},
    "worth_the_price": {"topic": "premium|price|pay|value|money", "area": "pricing",
        "cues": ["worth the money", "happy to pay", "good value"]},
}


def _contains(text: str, pattern: str) -> bool:
    return re.search(pattern, text) is not None


def classify_text(text: str, themes: list[str]) -> tuple[str | None, str]:
    """(theme or None, relevance) for one text and the themes of the supplied taxonomy. Pure keyword rules."""
    low = text.lower()
    topic_seen = False
    for theme in themes:                      # the taxonomy order; the first theme whose cue matches wins
        rule = RULES.get(theme)
        if rule is None or not _contains(low, rule["topic"]):
            continue
        topic_seen = True
        if any(cue in low for cue in rule["cues"]):
            return theme, "direct"
    return (None, "adjacent") if topic_seen else (None, "not_relevant")


class StubClassifierClient:
    """An LlmClient that classifies with keyword rules. Counts its calls (tests assert the cache prevents repeat calls)."""

    def __init__(self) -> None:
        self.calls: list[LlmRequest] = []
        self.texts_seen: list[str] = []

    @property
    def call_count(self) -> int:
        return len(self.calls)

    def complete(self, request: LlmRequest) -> LlmResponse:
        self.calls.append(request)
        payload = json.loads(request.user)
        themes = [t["theme"] for t in payload["taxonomy"]["themes"]]
        out = []
        for item in payload["texts"]:
            body = item["text"]
            if body.startswith("<untrusted_customer_text>") and body.endswith("</untrusted_customer_text>"):
                body = body[len("<untrusted_customer_text>"):-len("</untrusted_customer_text>")]
            text = html.unescape(body)
            self.texts_seen.append(text)
            theme, relevance = classify_text(text, themes)
            out.append({"text_ref": item["text_ref"], "theme": theme, "relevance": relevance})
        return LlmResponse(text=json.dumps({"classifications": out}), model=MODEL, request_id=f"stub:{len(self.calls)}",
                           provenance=PROVENANCE_STUB)
