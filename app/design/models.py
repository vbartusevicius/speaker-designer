"""Typed domain models replacing untyped dict clumps across design, catalog, and simulation layers."""
from __future__ import annotations

from dataclasses import asdict, dataclass, field
from typing import TYPE_CHECKING, Any, Optional

if TYPE_CHECKING:
    from ..physics.driver import Driver
    from ..physics.enclosure import Box
    from .cabinet import Geometry


@dataclass(frozen=True)
class PriceQuote:
    price_eur: float
    currency: str
    in_stock: bool
    sku: Optional[str]
    url: str
    checked: str
    ts: float
    cached: bool = False

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)

    @classmethod
    def from_dict(cls, data: dict[str, Any], cached: bool = True) -> "PriceQuote":
        return cls(
            price_eur=float(data["price_eur"]),
            currency=str(data.get("currency", "EUR")),
            in_stock=bool(data.get("in_stock", True)),
            sku=data.get("sku"),
            url=str(data["url"]),
            checked=str(data.get("checked", "")),
            ts=float(data.get("ts", 0.0)),
            cached=cached,
        )


@dataclass(frozen=True)
class ReplacementCandidate:
    driver: dict[str, Any]
    id: str
    brand: str
    model: str
    role: str
    nominal_mm: float
    match_pct: int
    notes: list[str]
    shop_url: Optional[str]
    price_eur: Optional[float]
    in_stock: Optional[bool]
    in_catalog: bool = True

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass
class DampingPlan:
    material: str
    lining_mm: int
    walls: list[str]
    fill_pct: int
    fill_note: str
    keep_clear_mm: int
    mid_chamber: Optional[str]
    note: str

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass
class ResolvedContext:
    design: dict[str, Any]
    W: Driver
    n: int
    M: Optional[Driver]
    T: Driver
    g: Geometry
    chamber: Optional[dict[str, Any]]
    volumes: dict[str, Any]
    box: Box
    port: Optional[dict[str, Any]]
    alignments: dict[str, Any]
    mid_fc: Optional[float]
    clearances: list[dict[str, Any]]
    layout_issues: list[dict[str, Any]]
    warnings: list[str] = field(default_factory=list)
    notes: list[str] = field(default_factory=list)
