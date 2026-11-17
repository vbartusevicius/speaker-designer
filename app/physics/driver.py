"""Loudspeaker driver model built from Thiele/Small small-signal parameters.

Only the published "primary" parameters are required (Fs, Qms, Qes, Vas, Re, Sd, Le);
the electro-mechanical parameters (Cms, Mms, Bl, Rms) are derived the same way
WinISD / BassBox / VituixCAD do it, so datasheets that omit them can still be simulated.
Tweeters and closed-back midranges may omit Vas; they are simulated with the
impedance-resonance model instead of a box model.
"""
from __future__ import annotations

import math
from dataclasses import asdict, dataclass, field
from typing import Optional

from .constants import C, RHO

ROLES = ("woofer", "midwoofer", "mid", "tweeter", "fullrange")


@dataclass
class Driver:
    id: str
    brand: str
    model: str
    role: str
    nominal_mm: float  # nominal size class in mm (EU convention, e.g. 220 for a "22 cm" woofer)
    price_eur: float
    Re: float
    Le_mH: float
    Fs: float
    Qms: float
    Qes: float
    Sd_cm2: float
    sens_db: float  # datasheet SPL @ 2.83 V / 1 m
    Z_nom: float
    outer_d_mm: float
    cutout_d_mm: float
    depth_mm: float
    Vas_L: Optional[float] = None
    Xmax_mm: float = 0.5
    Pe_W: float = 50.0
    flange_mm: float = 5.0
    bolt_circle_mm: Optional[float] = None
    bolt_count: int = 4
    bolt_hole_mm: float = 4.5
    fmin: float = 20.0
    fmax: float = 20000.0
    tier: int = 3  # 1 budget ... 5 high-end (subjective series grade)
    sealed_back: bool = False
    notes: str = ""
    verified: bool = False
    dims_verified: bool = False
    shop: Optional[dict] = None  # {"name", "url", "price_eur", "in_stock", "checked"}
    custom: bool = False
    extra: dict = field(default_factory=dict)

    # ---- derived parameters -------------------------------------------------
    @property
    def Qts(self) -> float:
        return self.Qms * self.Qes / (self.Qms + self.Qes)

    @property
    def Sd(self) -> float:
        return self.Sd_cm2 * 1e-4

    @property
    def Vas(self) -> Optional[float]:
        return None if self.Vas_L is None else self.Vas_L * 1e-3

    @property
    def ws(self) -> float:
        return 2 * math.pi * self.Fs

    @property
    def has_box_model(self) -> bool:
        return self.Vas_L is not None and self.Vas_L > 0 and not self.sealed_back

    @property
    def Cms(self) -> Optional[float]:
        if self.Vas is None:
            return None
        return self.Vas / (RHO * C ** 2 * self.Sd ** 2)

    @property
    def Mms(self) -> float:
        if self.Cms is None:
            return float(self.extra.get("Mms_g", 0.4)) * 1e-3
        return 1.0 / (self.ws ** 2 * self.Cms)

    @property
    def Bl(self) -> float:
        return math.sqrt(self.ws * self.Mms * self.Re / self.Qes)

    @property
    def Rms(self) -> float:
        return self.ws * self.Mms / self.Qms

    @property
    def eta0(self) -> Optional[float]:
        if self.Vas is None:
            return None
        return 4 * math.pi ** 2 * self.Fs ** 3 * self.Vas / (C ** 3 * self.Qes)

    @property
    def spl_1w_calc(self) -> Optional[float]:
        e = self.eta0
        return None if e is None else 112.1 + 10 * math.log10(e)

    @property
    def spl_2v83_calc(self) -> Optional[float]:
        s = self.spl_1w_calc
        return None if s is None else s + 10 * math.log10(8.0 / self.Re)

    @property
    def EBP(self) -> float:
        return self.Fs / self.Qes

    @property
    def Vd_cm3(self) -> float:
        return self.Sd_cm2 * self.Xmax_mm / 10.0

    @property
    def cone_d_mm(self) -> float:
        return 2000.0 * self.piston_radius

    @property
    def in_stock(self) -> bool:
        return bool((self.shop or {}).get("in_stock", True))

    @property
    def piston_radius(self) -> float:
        return math.sqrt(self.Sd / math.pi)

    @property
    def effective_bolt_circle(self) -> float:
        return self.bolt_circle_mm or round((self.outer_d_mm + self.cutout_d_mm) / 2.0 + 2, 1)

    @property
    def displacement_L(self) -> float:
        """Rough volume the driver body occupies inside the box (basket + magnet)."""
        r = self.cutout_d_mm / 2.0 / 1000.0
        return math.pi * r ** 2 * (self.depth_mm / 1000.0) * 0.45 * 1000.0

    def alignment_hint(self) -> str:
        if self.EBP < 50:
            return "sealed"
        if self.EBP > 90:
            return "vented"
        return "sealed or vented"

    def to_dict(self) -> dict:
        d = asdict(self)
        d.update(
            Qts=round(self.Qts, 3),
            Cms_mm_per_N=None if self.Cms is None else round(self.Cms * 1e3, 4),
            Mms_g=round(self.Mms * 1e3, 3),
            Bl=round(self.Bl, 3),
            Rms=round(self.Rms, 3),
            EBP=round(self.EBP, 1),
            eta0_pct=None if self.eta0 is None else round(self.eta0 * 100, 3),
            spl_2v83_calc=None if self.spl_2v83_calc is None else round(self.spl_2v83_calc, 1),
            Vd_cm3=round(self.Vd_cm3, 1),
            alignment_hint=self.alignment_hint(),
            bolt_circle_eff_mm=self.effective_bolt_circle,
            cone_d_mm=round(self.cone_d_mm, 0),
            in_stock=self.in_stock,
        )
        return d

    @classmethod
    def from_dict(cls, d: dict) -> "Driver":
        names = {f for f in cls.__dataclass_fields__}
        d = dict(d)
        if "nominal_mm" not in d and "size_in" in d:  # legacy imperial input
            d["nominal_mm"] = round(float(d["size_in"]) * 25.4, 0)
        kw = {k: v for k, v in d.items() if k in names}
        return cls(**kw)
