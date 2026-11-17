"""Lumped-element (Thiele/Small/Small) loudspeaker + enclosure simulator.

Electrical:  Ze = Re + K*(jw)^n   (semi-inductance fitted so |ZL(1 kHz)| = w*Le)
Mechanical:  Zm = Rms + jw*Mms + 1/(jw*Cms)
Acoustic box (seen from the cone, parallel branches):
    compliance Cab = Vb/(rho c^2) (+ absorption loss Rab from Qa)
    leakage    Ral = Ql/(wb*Cab)
    port       Zp  = Rap + jw*Map, Map = rho*Leff/Sp, Rap from Qp
Cone velocity: v = Bl*V / (Ze*(Zm + N*Sd^2*Za) + Bl^2)
Radiated volume velocity (cone + port + leak): U = Ud * Za/Zc
Half-space pressure at r: p = jw*rho*U/(2*pi*r)

This is the same equivalent circuit WinISD, BassBox and VituixCAD Enclosure use.
"""
from __future__ import annotations

import math
from dataclasses import dataclass
from typing import Optional

import numpy as np

from .constants import C, P_REF, PORT_VELOCITY_LIMIT, RHO, SQRT2
from .driver import Driver

SEMI_N = 0.7  # semi-inductance exponent (lossy voice coil)


def freq_axis(fmin: float = 10.0, fmax: float = 20000.0, n: int = 400) -> np.ndarray:
    return np.geomspace(fmin, fmax, n)


@dataclass
class Box:
    kind: str = "sealed"  # sealed | vented | infinite | closed (driver's own back chamber)
    Vb_L: float = 50.0
    fb: Optional[float] = None
    port_area_cm2: float = 0.0  # total of all ports
    port_leff_mm: float = 0.0  # acoustic length incl. end correction
    Ql: float = 7.0
    Qa: float = 100.0
    Qp: float = 100.0
    fill: float = 0.0  # 0..1, stuffing raises effective volume up to ~+20 %

    @property
    def Vb_eff(self) -> float:
        return self.Vb_L * 1e-3 * (1.0 + 0.2 * max(0.0, min(1.0, self.fill)))


def semi_inductance(le_mH: float, w: np.ndarray) -> np.ndarray:
    if le_mH <= 0:
        return np.zeros_like(w, dtype=complex)
    w0 = 2 * math.pi * 1000.0
    k = le_mH * 1e-3 * w0 / (w0 ** SEMI_N)
    return k * (1j * w) ** SEMI_N


def _lp2(f: np.ndarray, fc: float, q: float = 0.707) -> np.ndarray:
    s = 1j * f / fc
    return 1.0 / (s ** 2 + s / q + 1.0)


def _hp2(f: np.ndarray, fc: float, q: float) -> np.ndarray:
    s = 1j * f / fc
    return s ** 2 / (s ** 2 + s / q + 1.0)


@dataclass
class SimResult:
    f: np.ndarray
    p: np.ndarray  # complex pressure (Pa) at 1 m, half space, for vin
    zin: np.ndarray  # electrical input impedance of the driver group
    x_peak_mm: np.ndarray
    port_vel_peak: Optional[np.ndarray]
    vin: float
    re_total: float
    pe_total: float
    xmax_mm: float

    @property
    def spl(self) -> np.ndarray:
        return 20 * np.log10(np.abs(self.p) / P_REF + 1e-30)

    @property
    def p_per_volt(self) -> np.ndarray:
        return self.p / self.vin

    def group_delay_ms(self) -> np.ndarray:
        return group_delay_ms(self.f, self.p)

    def max_spl(self, port_limit: Optional[float] = PORT_VELOCITY_LIMIT) -> dict:
        v_th = math.sqrt(self.pe_total * self.re_total)
        v_x = self.vin * self.xmax_mm / np.maximum(self.x_peak_mm, 1e-12)
        vmax = np.minimum(v_x, v_th)
        limit = np.where(v_x < v_th, "xmax", "thermal").astype(object)
        if self.port_vel_peak is not None and port_limit:
            v_p = self.vin * port_limit / np.maximum(self.port_vel_peak, 1e-12)
            limit = np.where(v_p < vmax, "port", limit)
            vmax = np.minimum(vmax, v_p)
        spl = self.spl + 20 * np.log10(vmax / self.vin)
        return {"spl": spl, "vmax": vmax, "limit": limit, "v_thermal": v_th}


def group_delay_ms(f: np.ndarray, h: np.ndarray) -> np.ndarray:
    ph = np.unwrap(np.angle(h))
    w = 2 * math.pi * f
    return -np.gradient(ph, w) * 1000.0


def simulate(driver: Driver, box: Box, f: np.ndarray, vin: float = 2.83, n: int = 1,
             wiring: str = "parallel", use_le: bool = True, breakup: bool = True) -> SimResult:
    if not driver.has_box_model or box.kind == "closed":
        return simulate_closed(driver, f, vin, n, wiring)

    w = 2 * math.pi * f
    s = 1j * w
    v_each = vin / n if wiring == "series" else vin
    ze = driver.Re + (semi_inductance(driver.Le_mH, w) if use_le else 0)
    cms = driver.Cms
    assert cms is not None
    zm = driver.Rms + s * driver.Mms + 1.0 / (s * cms)
    sd = driver.Sd

    port_vel = None
    if box.kind == "infinite":
        za = np.zeros_like(s)
        ratio = np.ones_like(s)
    else:
        cab = box.Vb_eff / (RHO * C ** 2)
        zc_pure = 1.0 / (s * cab)
        if box.kind == "vented":
            sp = box.port_area_cm2 * 1e-4
            leff = box.port_leff_mm * 1e-3
            map_ = RHO * leff / sp
            wb = 1.0 / math.sqrt(map_ * cab)
            zp = wb * map_ / box.Qp + s * map_
        else:
            wb = driver.ws * math.sqrt(1.0 + (driver.Vas or 0) * n / box.Vb_eff)
            zp = None
        rab = 1.0 / (wb * cab * box.Qa)
        zc = zc_pure + rab
        ral = box.Ql / (wb * cab)
        y = 1.0 / zc + 1.0 / ral + (1.0 / zp if zp is not None else 0)
        za = 1.0 / y
        ratio = za / zc  # radiated / cone volume velocity

    zmb = zm + n * sd ** 2 * za
    v = driver.Bl * v_each / (ze * zmb + driver.Bl ** 2)
    zin_each = ze + driver.Bl ** 2 / zmb
    ud = n * sd * v
    u = ud * ratio
    if box.kind == "vented":
        up = -ud * za / zp
        port_vel = np.abs(up) / (box.port_area_cm2 * 1e-4) * SQRT2
    p = 1j * w * RHO * u / (2 * math.pi * 1.0)
    if breakup and driver.fmax < 20000:
        p = p * _lp2(f, driver.fmax * 1.6, 0.6)
    x = np.abs(v / s) * SQRT2 * 1000.0
    zin = zin_each / n if wiring == "parallel" else zin_each * n
    re_tot = driver.Re / n if wiring == "parallel" else driver.Re * n
    return SimResult(f, p, zin, x, port_vel, vin, re_tot, driver.Pe_W * n, driver.Xmax_mm)


def simulate_closed(driver: Driver, f: np.ndarray, vin: float = 2.83, n: int = 1,
                    wiring: str = "parallel") -> SimResult:
    """Driver with its own sealed back chamber (tweeters, closed-back mids).

    Response: datasheet sensitivity * 2nd-order high-pass at Fs/Qts * mild top roll-off.
    Impedance: Re + semi-inductance + parallel resonance circuit (Res = Re*Qms/Qes).
    """
    w = 2 * math.pi * f
    qts = driver.Qts
    p0 = P_REF * 10 ** (driver.sens_db / 20.0) * (vin / 2.83)
    h = _hp2(f, driver.Fs, qts)
    if driver.fmax < 40000:
        h = h * _lp2(f, max(driver.fmax * 1.25, 18000.0), 0.6)
    if n > 1:
        h = h * n if wiring == "parallel" else h
    res = driver.Re * driver.Qms / driver.Qes
    zmot = res / (1 + 1j * driver.Qms * (f / driver.Fs - driver.Fs / f))
    zin_each = driver.Re + semi_inductance(driver.Le_mH, w) + zmot
    zin = zin_each / n if wiring == "parallel" else zin_each * n
    # excursion estimate (only meaningful near Fs); piston volume velocity from pressure
    u = np.abs(p0 * h) * 2 * math.pi / (w * RHO)
    x = u / (driver.Sd * n * w) * SQRT2 * 1000.0
    re_tot = driver.Re / n if wiring == "parallel" else driver.Re * n
    return SimResult(f, p0 * h, zin, x, None, vin, re_tot, driver.Pe_W * n, driver.Xmax_mm)


# ---- response metrics -----------------------------------------------------------

def reference_level(f: np.ndarray, spl: np.ndarray, f_lo: float, f_hi: float) -> float:
    m = (f >= f_lo) & (f <= f_hi)
    return float(np.median(spl[m])) if m.any() else float(np.max(spl))


def f_minus(f: np.ndarray, spl: np.ndarray, ref: float, db: float = 3.0, f_start: float = 300.0) -> float:
    """Lowest frequency where response is still within -db of ref, scanning down from f_start."""
    idx = np.where(f <= f_start)[0]
    if idx.size == 0:
        return float(f[0])
    for i in idx[::-1]:
        if spl[i] < ref - db:
            if i + 1 < len(f):
                f1, f2, s1, s2 = f[i], f[i + 1], spl[i], spl[i + 1]
                t = (ref - db - s1) / (s2 - s1) if s2 != s1 else 0
                return float(math.exp(math.log(f1) + t * (math.log(f2) - math.log(f1))))
            return float(f[i])
    return float(f[0])


def bass_metrics(sim: SimResult, driver: Driver) -> dict:
    spl = sim.spl
    f = sim.f
    hi = min(400.0, driver.fmax / 2)
    lo = min(max(5 * driver.Fs, 120.0), hi * 0.8)
    ref = reference_level(f, spl, lo, hi)
    f3 = f_minus(f, spl, ref, 3, lo)
    f6 = f_minus(f, spl, ref, 6, lo)
    f10 = f_minus(f, spl, ref, 10, lo)
    band = (f > 1.4 * f3) & (f < hi)
    peak = float(np.max(spl[band]) - ref) if band.any() else 0.0
    dip = float(ref - np.min(spl[band])) if band.any() else 0.0
    return {"ref_db": ref, "f3": f3, "f6": f6, "f10": f10, "peak_db": peak, "dip_db": dip}
