"""Shared math, signal-processing, and dict utilities for design modules."""
from __future__ import annotations

import copy
import math

import numpy as np

from ..physics.constants import P_REF


def deep_merge(base: dict, over: dict | None) -> dict:
    out = copy.deepcopy(base)
    for k, v in (over or {}).items():
        if isinstance(v, dict) and isinstance(out.get(k), dict):
            out[k] = deep_merge(out[k], v)
        else:
            out[k] = copy.deepcopy(v)
    return out


def mag_db(x) -> np.ndarray:
    return 20 * np.log10(np.abs(x) + 1e-30)


def spl_db(p) -> np.ndarray:
    return 20 * np.log10(np.abs(p) / P_REF + 1e-30)


def smooth_db(f, y, frac: int = 6) -> np.ndarray:
    lf = np.log2(f)
    out = np.empty_like(y)
    half = 0.5 / frac
    for i, c in enumerate(lf):
        m = (lf >= c - half) & (lf <= c + half)
        out[i] = y[m].mean()
    return out


def band_median(f, y, lo: float, hi: float) -> float:
    if hi <= lo:
        c = math.sqrt(lo * hi) if lo > 0 and hi > 0 else lo
        lo, hi = c / 1.2, c * 1.2
    m = (f >= lo) & (f <= hi)
    return float(np.median(y[m])) if m.any() else float(np.median(y))


def round_nested(o):
    if isinstance(o, dict):
        return {k: round_nested(v) for k, v in o.items()}
    if isinstance(o, float):
        return round(o, 3)
    return o
