"""Crossover design and simulation.

Active (DSP): ideal Linkwitz-Riley 4th-order (LR4) electrical filters per way.
Passive: 2nd-order ladder networks (LR2 / Butterworth), Zobel impedance compensation,
L-pad attenuation; the network is simulated against the driver's *complex* impedance
(from the T/S model), like XSim / VituixCAD do with ZMA files.
"""
from __future__ import annotations

import math
from typing import Optional

import numpy as np


def _s(f, fc):
    return 1j * np.asarray(f) / fc


def butter2_lp(f, fc):
    s = _s(f, fc)
    return 1 / (s ** 2 + math.sqrt(2) * s + 1)


def butter2_hp(f, fc):
    s = _s(f, fc)
    return s ** 2 / (s ** 2 + math.sqrt(2) * s + 1)


def lr2_lp(f, fc):
    s = _s(f, fc)
    return 1 / (s + 1) ** 2


def lr2_hp(f, fc):
    s = _s(f, fc)
    return s ** 2 / (s + 1) ** 2


def lr4_lp(f, fc):
    return butter2_lp(f, fc) ** 2


def lr4_hp(f, fc):
    return butter2_hp(f, fc) ** 2


FILTERS = {"LR4": (lr4_lp, lr4_hp), "LR2": (lr2_lp, lr2_hp), "BW2": (butter2_lp, butter2_hp)}

# 2nd-order passive coefficients: L = kL*R/f [H], C = kC/(R*f) [F]
PASSIVE_COEF = {"LR2": (1 / math.pi, 1 / (4 * math.pi)), "BW2": (math.sqrt(2) / (2 * math.pi), 1 / (2 * math.sqrt(2) * math.pi))}


def passive_lc(fc: float, r: float, kind: str = "LR2") -> tuple[float, float]:
    kl, kc = PASSIVE_COEF[kind]
    return kl * r / fc, kc / (r * fc)


def zobel(re: float, le_mH: float) -> dict:
    rz = 1.25 * re
    cz = le_mH * 1e-3 / rz ** 2
    return {"R": rz, "C": cz}


def lpad(z: float, atten_db: float) -> dict:
    if atten_db < 1.0:  # below 1 dB an L-pad is not worth the parts
        return {"Rs": 0.0, "Rp": None}
    a = 10 ** (-atten_db / 20)
    return {"Rs": z * (1 - a), "Rp": z * a / (1 - a)}


E12 = [1.0, 1.2, 1.5, 1.8, 2.2, 2.7, 3.3, 3.9, 4.7, 5.6, 6.8, 8.2]


def nearest_e12(v: float) -> float:
    if v <= 0:
        return v
    dec = 10 ** math.floor(math.log10(v))
    cands = [m * dec for m in E12] + [10 * dec]
    return min(cands, key=lambda c: abs(math.log(c / v)))


# ---- ladder network simulation ------------------------------------------------
# A network is a list of elements applied from the amplifier towards the driver:
#   ("series", kind, value) or ("shunt", kind, value)  kind in L, C, R, ZOBEL(R,C)

def _z(kind: str, val, w):
    if kind == "L":
        return 1j * w * val + 0.0  # ideal inductor; DCR added separately as R
    if kind == "C":
        return 1 / (1j * w * val)
    if kind == "R":
        return np.full_like(w, val, dtype=complex)
    if kind == "RC":
        r, c = val
        return r + 1 / (1j * w * c)
    raise ValueError(kind)


def ladder(network: list, zload: np.ndarray, f: np.ndarray) -> tuple[np.ndarray, np.ndarray]:
    """Return (voltage transfer V_load/V_in, input impedance) of the ladder with load."""
    w = 2 * math.pi * f
    # Walk from load back to source keeping Z and the transfer ratio.
    z = zload.astype(complex)
    h = np.ones_like(z)
    for pos, kind, val in reversed(network):
        ze = _z(kind, val, w)
        if pos == "shunt":
            z = z * ze / (z + ze)
        else:
            h = h * z / (z + ze)
            z = z + ze
    return h, z


# Standard values stocked by EU crossover-part shops (MKP film caps, air-core / cored coils, 10 W resistors).
CAP_UF = [1.0, 1.5, 2.2, 2.7, 3.3, 3.9, 4.7, 5.6, 6.8, 8.2, 10, 12, 15, 18, 22, 27, 33, 39, 47, 56, 68, 82, 100]
COIL_MH = [0.10, 0.12, 0.15, 0.18, 0.22, 0.27, 0.33, 0.39, 0.47, 0.56, 0.68, 0.82, 1.0, 1.2, 1.5, 1.8, 2.2, 2.7,
           3.3, 3.9, 4.7, 5.6, 6.8, 8.2, 10.0]
RES_OHM = [0.47, 0.68, 1.0, 1.2, 1.5, 1.8, 2.2, 2.7, 3.3, 3.9, 4.7, 5.6, 6.8, 8.2, 10, 12, 15, 18, 22, 27, 33]


def cap_build(uf: float) -> dict:
    """Nearest single standard cap, or a 2-cap parallel combination if that is closer than 3 %."""
    single = min(CAP_UF, key=lambda c: abs(c - uf))
    best = ([single], abs(single - uf) / uf)
    if best[1] > 0.03:
        for a in CAP_UF:
            for b in CAP_UF:
                if b > a:
                    continue
                err = abs(a + b - uf) / uf
                if err < best[1] - 1e-9:
                    best = ([a, b], err)
    vals, err = best
    return {"values": vals, "total": round(sum(vals), 2), "error_pct": round(err * 100, 1),
            "build": " + ".join(f"{v:g} µF" for v in vals) + (" in parallel" if len(vals) > 1 else "")}


def nearest(series, v):
    return min(series, key=lambda c: abs(c - v))


AMP_W, Z_NOM = 100.0, 8.0  # rating basis: up to a 100 W / 8 ohm amplifier
V_PK = (2 * AMP_W * Z_NOM) ** 0.5  # ~40 V peak


def _details(kind, value, position, role):
    if kind == "C":
        uf = value * 1e6
        d = ["polypropylene film (MKP), NON-polar - never a polarised electrolytic, never ceramic",
             f"voltage >= 100 V DC (peak signal ~{V_PK:.0f} V; 250 V DC types are common and fine)",
             "tolerance ±5 % (±2-3 % for the tweeter if you can)"]
        if uf > 30 and role == "woofer" and "shunt" in position:
            d[0] = "MKP film, or a BIPOLAR (non-polar) electrolytic ≥ 100 V is acceptable in this woofer shunt position"
        return d
    if kind == "L":
        mh = value * 1e3
        cored = role == "woofer" and mh > 1.0
        irms = (AMP_W / Z_NOM) ** 0.5
        return [("ferrite/iron core (P-core or I-core), saturation current >= 10 A" if cored else "air-core (no saturation, lowest distortion)"),
                ("wire 1.2-1.4 mm, DCR <= 0.3 ohm (each 0.1 ohm costs woofer damping)" if role == "woofer" else "wire 0.8-1.0 mm, DCR <= 0.5 ohm"),
                f"current {irms:.1f} A rms continuous at 100 W; tolerance ±3 %"]
    return ["non-inductive metal-oxide (MOX) or cement/wirewound-free type" if role == "tweeter" else "metal-oxide (MOX) or cement resistor",
            "power rating 10 W (20 W if you play very loud); tolerance ±5 %"]


def _part(ref, kind, value, position, role):
    return {**_part0(ref, kind, value, position, role), "details": _details(kind, value, position, role)}


def _part0(ref, kind, value, position, role):
    if kind == "C":
        b = cap_build(value * 1e6)
        return {"ref": ref, "type": "capacitor", "value": round(value * 1e6, 2), "unit": "µF", "position": position,
                "build": b["build"], "build_error_pct": b["error_pct"], "use_value": b["total"],
                "spec": "MKP polypropylene film, >= 100 V" + (" (bipolar electrolytic is OK here)" if value * 1e6 > 30 and role == "woofer" and position == "shunt" else ""),
                "est_eur": round(sum(1.2 + 0.11 * v for v in b["values"]), 2)}
    if kind == "L":
        mh = value * 1e3
        use = nearest(COIL_MH, mh)
        if abs(use - mh) / mh > 0.03 and use < mh:  # can unwind a coil, not add turns
            use = min([c for c in COIL_MH if c >= mh] or [COIL_MH[-1]])
        cored = role == "woofer" and mh > 1.0
        return {"ref": ref, "type": "inductor", "value": round(mh, 3), "unit": "mH", "position": position,
                "build": f"{use:g} mH" + (" (unwind turns to fine-tune)" if abs(use - mh) / mh > 0.03 else ""), "use_value": use,
                "build_error_pct": round(abs(use - mh) / mh * 100, 1),
                "spec": ("ferrite/iron-core, 1.0-1.4 mm wire, DCR <= 0.4 ohm" if cored else "air-core, 0.8-1.2 mm wire (low distortion)"),
                "est_eur": round((6 + 1.6 * mh) if cored else (4 + 4.5 * mh), 2)}
    use = nearest(RES_OHM, value)
    return {"ref": ref, "type": "resistor", "value": round(value, 2), "unit": "Ω", "position": position,
            "build": f"{use:g} Ω", "use_value": use, "build_error_pct": round(abs(use - value) / value * 100, 1),
            "spec": "10 W metal-oxide or cement resistor", "est_eur": 1.5}


def build_passive(role: str, fx_low: Optional[float], fx_high: Optional[float], r_nom: float,
                  re: float, le_mH: float, atten_db: float, kind: str = "LR2",
                  use_zobel: bool = True, inductor_dcr: float = 0.3) -> dict:
    """Design the passive branch for one way. Returns network, buildable parts list and schematic."""
    net, parts, sch = [], [], []
    n = {"C": 0, "L": 0, "R": 0}

    def add(pos, k, val, label_ref=None, show=True):
        net.append((pos, k, val))
        if not show:
            return
        if k == "RC":
            n["R"] += 1; n["C"] += 1
            pr = _part(f"R{n['R']}", "R", val[0], "Zobel, across driver", role)
            pc = _part(f"C{n['C']}", "C", val[1], "Zobel, across driver", role)
            parts.extend([pr, pc])
            sch.append({"pos": pos, "kind": "RC", "label": f"{pr['ref']} {pr['build']} + {pc['ref']} {pc['build']}", "note": "Zobel"})
            return
        n[k] += 1
        pt = _part(f"{k}{n[k]}", k, val, pos, role)
        parts.append(pt)
        sch.append({"pos": pos, "kind": k, "label": f"{pt['ref']} {pt['build']}"})

    if fx_low:  # high-pass section
        L, Cc = passive_lc(fx_low, r_nom, kind)
        add("series", "C", Cc)
        add("shunt", "L", L)
    if fx_high:  # low-pass section
        L, Cc = passive_lc(fx_high, r_nom, kind)
        add("series", "L", L)
        add("series", "R", inductor_dcr, show=False)
        add("shunt", "C", Cc)
    pad = lpad(r_nom, atten_db)
    if pad["Rs"]:
        add("series", "R", pad["Rs"])
        add("shunt", "R", pad["Rp"])
        sch[-2]["note"] = sch[-1]["note"] = "L-pad"
    if use_zobel and le_mH > 0.1 and role != "tweeter":
        zb = zobel(re, le_mH)
        add("shunt", "RC", (zb["R"], zb["C"]))
    return {"network": net, "parts": parts, "schematic": sch}


def protection_cap(f_mt: float, r: float) -> float:
    """Series DC/turn-on-thump protection cap for an actively driven tweeter (corner ~ f_mt/3)."""
    c = 1 / (2 * math.pi * (f_mt / 3.0) * r)
    return min([v for v in CAP_UF if v * 1e-6 >= c] or [CAP_UF[-1]]) * 1e-6


def soldering_guide(mode: str, bom: dict) -> dict:
    n_parts = sum(len(w["parts"]) for w in bom.values())
    n_caps = sum(1 for w in bom.values() for p in w["parts"] for _ in (p["build"].split("+") if p["type"] == "capacitor" else []))
    n_items = sum(len(p["build"].split("+")) if p["type"] == "capacitor" else 1 for w in bom.values() for p in w["parts"])
    joints = 2 * n_items + 2 * len(bom) + 2
    if mode == "active":
        steps = (["Solder the tweeter protection capacitor in series with the tweeter's + lead (or on a small tag strip "
                  "behind the terminals). It blocks DC and turn-on thumps from the DSP/amp."] if n_parts else []) + [
            "Wire every driver to its own terminal pair (3 per speaker); crimp or solder spade lugs.",
            "No crossover board needed: the DSP does the filtering."]
    else:
        steps = [
            "Mount all parts on a 6-9 mm plywood/MDF board with hot glue + zip ties (vibration-proof).",
            "Keep coils >= 5 cm apart and rotate neighbours 90 degrees to each other to avoid magnetic coupling.",
            "Build one board per speaker, or split it into a bass board and a mid/treble board (bi-wire ready).",
            "Parallel caps: twist the legs together and solder; keep leads short.",
            "Use 1.5 mm2 wire to the woofer, 0.75-1.0 mm2 to mid and tweeter; mark + / - and keep the polarity shown.",
            "Solder with a 40-60 W iron and rosin-core solder; insulate joints with heat-shrink.",
            "Before closing the box: measure each driver branch's DC resistance with a multimeter.",
            "Mount the board on the back panel or floor, away from the woofer magnet, reachable through the baffle hole.",
        ]
    return {"required": n_parts > 0, "parts": n_parts, "components_incl_parallel": n_items, "capacitors": n_caps,
            "solder_joints_est": joints if n_parts else 2 * len(bom), "steps": steps,
            "tools": ["soldering iron 40-60 W", "rosin-core solder 0.8-1 mm", "heat-shrink tubing", "multimeter",
                      "wire stripper", "hot-glue gun / zip ties"] if n_parts else ["crimp tool or soldering iron", "multimeter"]}
