"""Typed, immutable view of the NBE parameter file (nbe_params_v0.1.yaml)."""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass

from app.domain.errors import ParamsError


@dataclass(frozen=True)
class NbeAction:
    id: str
    description: str
    targets: tuple[str, ...]
    ceilings: Mapping[str, float]
    effort_band: str
    resolves_blockers: tuple[str, ...]
    supplies_evidence_type: str | None = None
    p2_ci_component_multiplier: float | None = None
    p2_concentration_component_multiplier: float | None = None
    d6_cap_lift_when_d4_at_least: float | None = None
    unblocks_scoring: bool = False


@dataclass(frozen=True)
class BlockerDependency:
    """While the gate reports `requires_resolved`, only an action that itself resolves `requires_resolved` may claim `blocker`."""
    blocker: str
    requires_resolved: str


@dataclass(frozen=True)
class NbeParams:
    version: str
    content_hash: str
    ddi_params_version: str
    effort_bands_days: Mapping[str, float]
    relevance_direct: float
    relevance_checklist_gap: float
    relevance_secondary: float
    applicability: Mapping[str, float]
    actions: tuple[NbeAction, ...]
    blocker_dependencies: tuple[BlockerDependency, ...] = ()      # empty for nbe_params_v0.1 (no dependency model)

    def effort_days(self, action: NbeAction) -> float:
        return float(self.effort_bands_days[action.effort_band])

    def may_claim_blocker(self, action: NbeAction, blocker: str, gate_codes: Sequence[str]) -> bool:
        """False when a dependency of `blocker` is currently reported by the gate and the action does not resolve it."""
        return not any(d.blocker == blocker and d.requires_resolved in gate_codes
                       and d.requires_resolved not in action.resolves_blockers for d in self.blocker_dependencies)

    @classmethod
    def from_mapping(cls, raw: Mapping, content_hash: str) -> NbeParams:
        try:
            actions = tuple(
                NbeAction(
                    id=a["id"], description=a["description"], targets=tuple(a["targets"]),
                    ceilings={k: float(v) for k, v in (a.get("ceilings") or {}).items()},
                    effort_band=a["effort_band"], resolves_blockers=tuple(a.get("resolves_blockers") or ()),
                    supplies_evidence_type=a.get("supplies_evidence_type"),
                    p2_ci_component_multiplier=a.get("p2_ci_component_multiplier"),
                    p2_concentration_component_multiplier=a.get("p2_concentration_component_multiplier"),
                    d6_cap_lift_when_d4_at_least=a.get("d6_cap_lift_when_d4_at_least"),
                    unblocks_scoring=bool(a.get("unblocks_scoring", False)))
                for a in raw["actions"])
            rel = raw["relevance_values"]
            params = cls(
                version=str(raw["version"]), content_hash=content_hash,
                ddi_params_version=str(raw["ddi_params_version"]),
                effort_bands_days={k: float(v) for k, v in raw["effort_bands_days"].items()},
                relevance_direct=float(rel["direct_or_critical_challenge"]),
                relevance_checklist_gap=float(rel["checklist_gap"]),
                relevance_secondary=float(rel["secondary_dimension"]),
                applicability={k: float(v) for k, v in raw["applicability"].items()},
                actions=actions,
                blocker_dependencies=tuple(
                    BlockerDependency(blocker=str(d["blocker"]), requires_resolved=str(d["requires_resolved"]))
                    for d in (raw.get("blocker_dependencies") or ())))
        except (KeyError, TypeError, ValueError) as exc:
            raise ParamsError(f"NBE parameter file is incomplete or malformed: {exc!r}") from exc
        for a in params.actions:
            if a.effort_band not in params.effort_bands_days:
                raise ParamsError(f"NBE action {a.id} uses unknown effort band {a.effort_band}")
        return params
