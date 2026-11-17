"""Classic alignments and numerical box optimisation for a fixed volume."""
from __future__ import annotations

import math

import numpy as np

from .driver import Driver
from .enclosure import Box, bass_metrics, freq_axis, simulate
from .port import port_length_mm


def sealed_for_qtc(d: Driver, qtc: float = 0.707, n: int = 1) -> dict:
    qts = d.Qts
    if qtc <= qts:
        return {"Vb_L": None, "fc": None, "f3": None, "note": f"Qts {qts:.2f} already above target Qtc"}
    alpha = (qtc / qts) ** 2 - 1
    assert d.Vas_L is not None
    vb = d.Vas_L * n / alpha
    fc = d.Fs * qtc / qts
    a = 1 / qtc ** 2 - 2
    f3 = fc * math.sqrt((a + math.sqrt(a * a + 4)) / 2)
    return {"Vb_L": vb, "fc": fc, "f3": f3, "qtc": qtc}


def sealed_qtc_for_volume(d: Driver, vb_L: float, n: int = 1) -> dict:
    assert d.Vas_L is not None
    alpha = d.Vas_L * n / vb_L
    qtc = d.Qts * math.sqrt(1 + alpha)
    fc = d.Fs * math.sqrt(1 + alpha)
    a = 1 / qtc ** 2 - 2
    f3 = fc * math.sqrt((a + math.sqrt(a * a + 4)) / 2)
    return {"Vb_L": vb_L, "qtc": qtc, "fc": fc, "f3": f3}


def qb3(d: Driver, n: int = 1) -> dict:
    """Keele's closed-form approximations of Small's QB3 vented alignment (0.2<Qts<0.5)."""
    qts = d.Qts
    return {"Vb_L": 15 * qts ** 2.87 * d.Vas_L * n, "fb": 0.42 * d.Fs * qts ** -0.9,
            "f3": 0.26 * d.Fs * qts ** -1.4, "valid": 0.2 <= qts <= 0.5}


_CACHE: dict = {}


def _key(d: Driver, *a):
    return (d.id, d.Fs, d.Qms, d.Qes, d.Vas_L, d.Sd_cm2, d.Re, d.fmax) + tuple(round(x, 2) if isinstance(x, float) else x for x in a)


def optimise_vented(d: Driver, vb_L: float, n: int = 1, max_peak_db: float = 1.0,
                    port_area_cm2: float = 50.0, Ql: float = 7.0, fill: float = 0.3) -> dict:
    k = _key(d, "v", vb_L, n, max_peak_db, port_area_cm2, Ql, fill)
    if k not in _CACHE:
        if len(_CACHE) > 5000:
            _CACHE.clear()
        _CACHE[k] = _optimise_vented(d, vb_L, n, max_peak_db, port_area_cm2, Ql, fill)
    return dict(_CACHE[k])


def _optimise_vented(d: Driver, vb_L: float, n: int = 1, max_peak_db: float = 1.0,
                     port_area_cm2: float = 50.0, Ql: float = 7.0, fill: float = 0.3) -> dict:
    """Sweep the tuning for a fixed volume; pick the lowest F3 with passband peak <= max_peak_db.

    Uses Le=0 so the bass alignment is judged without voice-coil roll-off.
    """
    f = freq_axis(10, 1000, 220)
    best = None
    for fb in np.arange(max(15.0, 0.55 * d.Fs), 2.2 * d.Fs, 0.5):
        leff = port_length_mm(vb_L * (1 + 0.2 * fill), fb, port_area_cm2, end_correction=0.0)
        box = Box("vented", vb_L, fb, port_area_cm2, leff, Ql=Ql, fill=fill)
        m = bass_metrics(simulate(d, box, f, n=n, use_le=False, breakup=False), d)
        ok = m["peak_db"] <= max_peak_db and m["dip_db"] <= 1.5
        key = (0 if ok else 1, m["f3"] if ok else m["peak_db"])
        if best is None or key < best[0]:
            best = (key, float(fb), m)
    assert best is not None
    _, fb, m = best
    return {"fb": fb, **m}


def sealed_metrics(d: Driver, vb_L: float, n: int = 1, fill: float = 0.6) -> dict:
    k = _key(d, "s", vb_L, n, fill)
    if k not in _CACHE:
        _CACHE[k] = _sealed_metrics(d, vb_L, n, fill)
    return dict(_CACHE[k])


def _sealed_metrics(d: Driver, vb_L: float, n: int = 1, fill: float = 0.6) -> dict:
    f = freq_axis(10, 1000, 220)
    m = bass_metrics(simulate(d, Box("sealed", vb_L, fill=fill), f, n=n, use_le=False, breakup=False), d)
    return {**sealed_qtc_for_volume(d, vb_L * (1 + 0.2 * fill), n), **m}


def choose_box_alignment(d: Driver, vb_L: float, n: int = 1, fill: float = 0.5, box_pref: str = "auto") -> tuple[str, dict, dict]:
    """Evaluate sealed and vented alignments for a fixed volume and resolve 'auto'."""
    sealed = sealed_metrics(d, vb_L, n, fill=max(fill, 0.6))
    vent = optimise_vented(d, vb_L, n, fill=fill)
    if box_pref == "auto":
        btype = "vented" if vent["f3"] < sealed["f3"] - 5 and d.Qts < 0.5 else "sealed"
    else:
        btype = box_pref
    return btype, sealed, vent
