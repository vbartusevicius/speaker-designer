"""SpeakerSystem Strategy Protocol & Registry (Open/Closed extension point).

Allows registering new speaker topologies (e.g. full-range, subwoofer, coaxial, dipole)
without modifying API routes or export handlers.
"""
from __future__ import annotations

from typing import Any, Protocol


class SpeakerSystem(Protocol):
    kind: str

    def simulate(self, design: dict[str, Any]) -> dict[str, Any]: ...
    def reverse(self, req: dict[str, Any]) -> dict[str, Any]: ...


class FullRangeSystem:
    kind = "full_range"

    def simulate(self, design: dict[str, Any]) -> dict[str, Any]:
        from .system import simulate_design
        return simulate_design(design)

    def reverse(self, req: dict[str, Any]) -> dict[str, Any]:
        from .optimizer import reverse
        return reverse(req)


class SubwooferSystem:
    kind = "sub"

    def simulate(self, design: dict[str, Any]) -> dict[str, Any]:
        from .sub import simulate_sub
        return simulate_sub(design)

    def reverse(self, req: dict[str, Any]) -> dict[str, Any]:
        from .sub import reverse_sub
        return reverse_sub(req)


SYSTEMS: dict[str, SpeakerSystem] = {
    "full_range": FullRangeSystem(),
    "sub": SubwooferSystem(),
}


def register_system(system: SpeakerSystem) -> None:
    """Register a custom speaker topology strategy."""
    SYSTEMS[system.kind] = system


def get_system(design_or_kind: dict[str, Any] | str) -> SpeakerSystem:
    kind = design_or_kind if isinstance(design_or_kind, str) else str(design_or_kind.get("system") or "full_range")
    return SYSTEMS.get(kind, SYSTEMS["full_range"])
