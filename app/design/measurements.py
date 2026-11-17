"""Measured driver data (FRD = frequency response, ZMA = impedance), as published by manufacturers
or exported from REW / ARTA / VituixCAD.  Text format: frequency, value[, phase] per line;
comment/header lines are ignored.  Missing phase (or all-zero phase, common in published files)
is replaced by the minimum phase computed from the magnitude (Hilbert transform via the cepstrum).
"""
from __future__ import annotations

import json
import math
import os
import re
from pathlib import Path

import numpy as np

from ..physics.constants import P_REF

KINDS = ("frd", "zma")


def root() -> Path:
    return Path(os.environ.get("MEASUREMENTS_PATH", Path(__file__).resolve().parents[2] / "userdata" / "measurements"))


def parse(text: str) -> dict:
    f, a, ph = [], [], []
    for line in text.splitlines():
        parts = [p for p in re.split(r"[\s,;]+", line.strip()) if p]
        try:
            nums = [float(p) for p in parts[:3]]
        except ValueError:
            continue
        if len(nums) < 2 or nums[0] <= 0:
            continue
        f.append(nums[0]); a.append(nums[1]); ph.append(nums[2] if len(nums) > 2 else 0.0)
    if len(f) < 10:
        raise ValueError("need at least 10 data lines: frequency, value[, phase]")
    order = np.argsort(f)
    fa, aa, pha = np.array(f)[order], np.array(a)[order], np.array(ph)[order]
    return {"f": fa.tolist(), "a": aa.tolist(), "phase": pha.tolist(), "has_phase": bool(np.any(np.abs(pha) > 0.5))}


def save(driver_id: str, kind: str, text: str, meta: dict | None = None) -> dict:
    if kind not in KINDS:
        raise ValueError("kind must be frd or zma")
    data = parse(text)
    d = root() / re.sub(r"[^A-Za-z0-9_.-]", "_", driver_id)
    d.mkdir(parents=True, exist_ok=True)
    (d / f"{kind}.json").write_text(json.dumps({**data, "meta": meta or {}}))
    return summary(driver_id)


def delete(driver_id: str, kind: str) -> bool:
    p = root() / re.sub(r"[^A-Za-z0-9_.-]", "_", driver_id) / f"{kind}.json"
    if p.exists():
        p.unlink()
        return True
    return False


def load(driver_id: str, kind: str) -> dict | None:
    p = root() / re.sub(r"[^A-Za-z0-9_.-]", "_", driver_id) / f"{kind}.json"
    return json.loads(p.read_text()) if p.exists() else None


def summary(driver_id: str) -> dict:
    out = {}
    for k in KINDS:
        m = load(driver_id, k)
        out[k] = None if m is None else {"points": len(m["f"]), "f_min": m["f"][0], "f_max": m["f"][-1],
                                         "has_phase": m["has_phase"], **m.get("meta", {})}
    return out


def minimum_phase(f: np.ndarray, mag_db: np.ndarray, fs: float = 96000.0, n: int = 1 << 15) -> np.ndarray:
    """Minimum phase (radians) at f for the given magnitude, via the folded real cepstrum."""
    fl = np.linspace(0, fs / 2, n // 2 + 1)
    lf = np.log(np.maximum(fl, fl[1]))
    lx = np.log(f)
    mag = np.interp(lf, lx, mag_db)
    # continue the measured slope (dB per ln-f) over the last octave beyond both ends, capped at 40 dB of roll-off
    lo = lx < lx[0] + math.log(2)
    hi = lx > lx[-1] - math.log(2)
    s_lo = np.polyfit(lx[lo], mag_db[lo], 1)[0] if lo.sum() > 2 else 0.0
    s_hi = np.polyfit(lx[hi], mag_db[hi], 1)[0] if hi.sum() > 2 else 0.0
    below, above = lf < lx[0], lf > lx[-1]
    mag[below] = np.maximum(mag_db[0] + s_lo * (lf[below] - lx[0]), mag_db[0] - 40)
    mag[above] = np.maximum(mag_db[-1] + s_hi * (lf[above] - lx[-1]), mag_db[-1] - 40)
    logm = mag / 20.0 * math.log(10)
    full = np.concatenate([logm, logm[-2:0:-1]])
    cep = np.fft.ifft(full).real
    w = np.zeros(n)
    w[0] = 1
    w[1:n // 2] = 2
    w[n // 2] = 1
    hmin = np.fft.fft(cep * w)
    phase = np.unwrap(np.imag(hmin[: n // 2 + 1]))
    return np.interp(f, fl, phase)


def response(m: dict, f: np.ndarray, vin: float = 2.83) -> np.ndarray:
    """Complex pressure (Pa at 1 m for vin) on the simulation grid; magnitude flat-extrapolated at the ends."""
    mf, ma = np.array(m["f"]), np.array(m["a"])
    db = np.interp(np.log(f), np.log(mf), ma)
    ph = (np.radians(np.interp(np.log(f), np.log(mf), np.unwrap(np.radians(m["phase"])) * 180 / math.pi))
          if m["has_phase"] else minimum_phase(f, db))
    return P_REF * 10 ** (db / 20) * (vin / 2.83) * np.exp(1j * ph)


def impedance(m: dict, f: np.ndarray) -> np.ndarray:
    mf, za = np.array(m["f"]), np.array(m["a"])
    mag = np.interp(np.log(f), np.log(mf), za)
    ph = np.radians(np.interp(np.log(f), np.log(mf), m["phase"])) if m["has_phase"] else np.zeros_like(f)
    return mag * np.exp(1j * ph)


def merge_low(model: np.ndarray, meas: np.ndarray, f: np.ndarray, f_merge: float) -> np.ndarray:
    """Use the box model below f_merge (it knows the box/port), the measurement above; the model is
    level-matched in a 1/3-octave band around f_merge and cross-faded over one octave."""
    band = (f > f_merge / 1.26) & (f < f_merge * 1.26)
    if band.any():
        gain = np.median(np.abs(meas[band])) / max(np.median(np.abs(model[band])), 1e-30)
        rot = np.exp(1j * np.median(np.angle(meas[band] / model[band])))
        model = model * gain * rot
    t = np.clip(np.log2(f / (f_merge / math.sqrt(2))), 0, 1)
    return model * (1 - t) + meas * t
