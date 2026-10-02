"""Decision lifecycle rules (docs/decision-lifecycle.md). Mirrors the database guard trigger.

Stage values are the database enum values. `decision_created` in older drafts means `created`.
The DB trigger `ddr_decision_lifecycle_guard` is the backstop. This module is the service-level
rule set so callers get a clear explanation before the database is reached.
"""

from __future__ import annotations

from app.domain.errors import StateConflict

STAGES = ("created", "evidence_gathered", "assessed", "challenged", "validated", "decided")

LEGAL_TRANSITIONS: frozenset[tuple[str, str]] = frozenset({
    ("created", "evidence_gathered"),
    ("evidence_gathered", "assessed"),
    ("assessed", "challenged"),
    ("challenged", "validated"),
    ("validated", "decided"),
    ("assessed", "evidence_gathered"),       # stale: evidence added/changed, canvas edited
    ("challenged", "evidence_gathered"),
    ("validated", "evidence_gathered"),      # stale, or a human recorded "defer"
})

STALE_RETURN_FROM = ("assessed", "challenged", "validated")

LABELS = {
    "created": "Decision created",
    "evidence_gathered": "Evidence gathered",
    "assessed": "Assessment run",
    "challenged": "Evidence challenged",
    "validated": "Assessment validated by review",     # exact wording required by LC-6 (never implies the decision is right)
    "decided": "Human decision recorded",
}

# Stages in which evidence may be written (a decided decision is immutable).
EVIDENCE_WRITABLE = ("created", "evidence_gathered", "assessed", "challenged", "validated")


def label(stage: str) -> str:
    return LABELS[stage]


def is_legal(from_stage: str, to_stage: str) -> bool:
    return (from_stage, to_stage) in LEGAL_TRANSITIONS


def require_legal(from_stage: str, to_stage: str) -> None:
    if from_stage == "decided":
        raise StateConflict("The decision is decided and immutable in the MVP.",
                            detail={"from": from_stage, "to": to_stage})
    if not is_legal(from_stage, to_stage):
        raise StateConflict(f"Illegal lifecycle transition {from_stage} -> {to_stage}.",
                            detail={"from": from_stage, "to": to_stage})
