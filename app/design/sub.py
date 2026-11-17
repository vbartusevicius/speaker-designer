"""Subwoofer: one to four woofers in a sealed or vented box, low-pass (+ subsonic high-pass for vented)
from a plate amplifier or DSP. Same box, port and layout physics as the full-range designer."""
from __future__ import annotations

import math
from typing import Any

import numpy as np

from ..physics import crossover as xo
from ..physics.alignments import choose_box_alignment, optimise_vented, qb3, sealed_for_qtc, sealed_metrics
from ..physics.enclosure import Box, freq_axis, simulate
from . import drivers_db
from .cabinet import damping_plan, geometry, volume_budget
from .layout import GAP, MARGIN, place_front_ports, validate_layout
from .ports import best_auto_port
from .utils import deep_merge, spl_db

DEFAULT_SUB = {
    "system": "sub", "name": "subwoofer",
    "cabinet": {"mode": "free", "outer_w": 380.0, "outer_h": 420.0, "outer_d": 400.0, "wall_t": 18.0, "baffle_t": 18.0,
                "fill": 0.5, "bracing_pct": 3.0},
    "drivers": {"woofer": {"id": "dayton-rss265hf-4", "count": 1, "wiring": "parallel"}, "mid": None, "tweeter": None},
    "box": {"type": "auto", "fb": None, "port": {"location": "front", "shape": "auto", "flared": False, "d_mm": None,
                                                 "count": None, "slot_w_mm": None}},
    "sub": {"lp_hz": 80.0, "lp_kind": "LR4", "subsonic": True, "amp_w": None},  # None = woofers' rated power
    "layout": {"positions": None, "min_web_mm": 10.0},
    "sim": {"points": 220},
}


def _layout(g, W, n):
    """Woofers centred, stacked along the longer side of the cavity."""
    r = W.outer_d_mm / 2
    cx, cy = g.open_x + g.open_w / 2, g.open_y + g.open_h / 2
    step = 2 * r + GAP
    vertical = g.open_h >= g.open_w
    return [{"x": cx if vertical else cx + (i - (n - 1) / 2) * step,
             "y": cy + (i - (n - 1) / 2) * step if vertical else cy} for i in range(n)]


def simulate_sub(design: dict) -> dict:
    d = deep_merge(DEFAULT_SUB, design)
    W = drivers_db.get(d["drivers"]["woofer"]["id"])
    if W is None:
        raise ValueError("unknown subwoofer driver")
    n = int(d["drivers"]["woofer"].get("count") or 1)
    g = geometry(d["cabinet"])
    sp = d["sub"]
    auto_amp = not sp.get("amp_w")
    warnings: list[str] = []
    notes: list[str] = []
    pos = d["layout"].get("positions") or {"woofer": _layout(g, W, n)}
    pos = {"woofer": pos["woofer"], **({"port": pos["port"]} if pos.get("port") else {})}
    vols = volume_budget(g, W, n, None, None, None)
    net, fill = vols["net_L"], g.fill
    btype, sealed, vent = choose_box_alignment(W, net, n, fill, d["box"]["type"])
    port = None
    if btype == "vented":
        fb = d["box"]["fb"] or vent["fb"]
        pw = sp.get("amp_w") or W.Pe_W * n
        cfg = d["box"]["port"]
        port = best_auto_port(W, n, g, net, fb, cfg, pw, fill)
        net = net - port.get("ext_volume_L", 0)
        box = Box("vented", net, fb, port["area_cm2"], port["leff_mm"], fill=fill)
        d["box"]["fb"] = round(fb, 1)
        if port["location"] in ("front", "rear") and port["shape"] == "round" and len(pos.get("port", [])) != port["count"]:
            occ = pos if port["location"] == "front" else {"woofer": []}
            pos["port"] = place_front_ports(g, occ, W, None, None, port, port["count"], "left", d["layout"]["min_web_mm"])
            if len(pos["port"]) < port["count"]:
                warnings.append(f"No free space for the {port['location']} port(s): use a slot, bottom or rear port.")
        if not port["fits"]:
            warnings.append(f"Port {port['length_mm']:.0f} mm is longer than the {port['max_len_mm']:.0f} mm available: use a slot, an elbow or a bigger box.")
    else:
        box = Box("sealed", net, fill=max(fill, 0.6))
    fp = port if port and port["location"] == "front" and port["shape"] == "round" else None
    warnings += [i["msg"] for i in validate_layout(g, pos, W, None, None, fp, d["layout"]["min_web_mm"]) if i["level"] == "error"]

    f = freq_axis(10, 400, int(d["sim"].get("points") or 220))
    s = simulate(W, box, f, 2.83, n, d["drivers"]["woofer"].get("wiring", "parallel"), breakup=False)
    lp = {"LR4": xo.lr4_lp, "LR2": xo.lr2_lp, "BW2": xo.butter2_lp}[sp["lp_kind"]](f, sp["lp_hz"])
    f_hp = round(0.8 * (box.fb or 20.0), 1) if (btype == "vented" and sp["subsonic"]) else (15.0 if sp["subsonic"] else None)
    hp = ((xo.lr4_hp if btype == "vented" else xo.butter2_hp)(f, f_hp)) if f_hp else np.ones_like(f)
    H = lp * hp
    x_per_sqrt_w = s.x_peak_mm * math.sqrt(s.re_total) / 2.83 * np.abs(hp * lp)
    band_x = (f >= 15) & (f <= 200)
    xmax_power = float((W.Xmax_mm / max(np.max(x_per_sqrt_w[band_x]), 1e-9)) ** 2)
    rated = W.Pe_W * n
    port_power = None
    if s.port_vel_peak is not None and port:
        v_per_sqrt_w = s.port_vel_peak * math.sqrt(s.re_total) / 2.83 * np.abs(hp)
        port_power = float((port["vel_limit_ms"] / max(np.max(v_per_sqrt_w[band_x]), 1e-9)) ** 2)
    if auto_amp:
        sp["amp_w"] = round(min(rated, xmax_power, port_power or 1e9), 0)
    v_amp = math.sqrt(sp["amp_w"] * s.re_total)
    k = v_amp / 2.83
    x_amp = s.x_peak_mm * k * np.abs(hp * lp)
    pv = s.port_vel_peak * k * np.abs(hp) if s.port_vel_peak is not None else None
    ms = s.max_spl()
    out_amp = spl_db(s.p * k * H)
    band = (f >= 30) & (f <= 80)
    box_spl = spl_db(s.p)
    f3 = sealed["f3"] if btype == "sealed" else vent["f3"] if not d["box"].get("fb") else _fx(f, box_spl, 3)
    xmax_use = float(np.max(x_amp[f >= 15]) / W.Xmax_mm)
    if xmax_use > 1.02:
        warnings.append(f"At {sp['amp_w']:.0f} W the cone exceeds Xmax ({xmax_use * 100:.0f} %) - lower the amplifier power, raise the subsonic filter or use a bigger box.")
    if pv is not None and port and float(np.max(pv[f >= 15])) > port["vel_limit_ms"] * 1.01:
        warnings.append(f"Port air speed {np.max(pv[f >= 15]):.1f} m/s at {sp['amp_w']:.0f} W exceeds {port['vel_limit_ms']:.0f} m/s: use a bigger or flared port.")
    if sp["amp_w"] > W.Pe_W * n * 1.5:
        warnings.append(f"The amplifier ({sp['amp_w']:.0f} W) is well above the woofers' rating ({W.Pe_W * n:.0f} W).")
    at = lambda arr, hz: float(np.interp(hz, f, arr))
    metrics = {"box_type": btype, "net_volume_L": round(net, 2), "fb_hz": round(box.fb, 1) if box.fb else None,
               "qtc": round(sealed.get("qtc", 0), 3) if btype == "sealed" else None,
               "woofer_f3_hz": round(_fx(f, box_spl, 3), 1), "woofer_f10_hz": round(_fx(f, box_spl, 10), 1),
               "sensitivity_db_2v83_1m": round(float(np.median(box_spl[band])), 1),
               "max_spl_20hz": round(at(ms["spl"], 20), 1), "max_spl_30hz": round(at(ms["spl"], 30), 1),
               "max_spl_40hz": round(at(ms["spl"], 40), 1), "max_spl_60hz": round(at(ms["spl"], 60), 1),
               "out_at_amp_40hz": round(at(out_amp, 40), 1), "xmax_use_pct": round(xmax_use * 100),
               "port_vel_peak_ms": round(float(np.max(pv[f >= 15])), 1) if pv is not None else None,
               "rated_power_w": rated, "xmax_power_w": round(xmax_power), "port_power_w": round(port_power) if port_power else None,
               "amp_w": sp["amp_w"],
               "price_drivers_eur": round(W.price_eur * n, 2), "subsonic_hz": f_hp, "lp_hz": sp["lp_hz"]}
    if port:
        port = {**port, "vel_peak_ms": metrics["port_vel_peak_ms"]}
    d["layout"]["positions"] = pos
    d["box"]["type"] = btype
    return {"system": "sub", "design": d, "geometry": g.to_dict(), "drivers": {"woofer": W.to_dict(), "mid": None, "tweeter": None},
            "port": port, "chamber": None, "volumes": vols, "metrics": metrics, "warnings": warnings, "notes": notes,
            "damping": damping_plan(btype == "vented", port, False), "clearances": [], "layout_issues": [],
            "curves": {"f": f.tolist(), "spl_box": spl_db(s.p).tolist(), "spl_out": out_amp.tolist(),
                       "filter_db": (20 * np.log10(np.abs(H) + 1e-12)).tolist(),
                       "max_spl": ms["spl"].tolist(), "max_spl_limit": [str(x) for x in ms["limit"]],
                       "excursion_mm": x_amp.tolist(), "xmax_mm": W.Xmax_mm,
                       "port_velocity_ms": pv.tolist() if pv is not None else None,
                       "impedance": np.abs(s.zin).tolist(), "impedance_phase": np.degrees(np.angle(s.zin)).tolist(),
                       "group_delay_ms": s.group_delay_ms().tolist(), "amp_w": sp["amp_w"]}}


def _fx(f, spl, down):
    ref = float(np.median(spl[(f >= 60) & (f <= 120)]))
    below = np.where(spl < ref - down)[0]
    below = below[f[below] < 60]
    return float(f[below[-1]]) if len(below) else float(f[0])


def reverse_sub(req: dict) -> dict:
    """Box for a given woofer (x count): sealed Qtc 0.707 or QB3 vented, golden-ratio outer size."""
    from .optimizer import _solve_dims
    W = drivers_db.get(req.get("woofer"))
    if W is None:
        raise ValueError("unknown subwoofer driver")
    n = int(req.get("woofer_count", 1))
    t = float(req.get("wall_t", 18))
    align = req.get("alignment", "auto")
    sv, vv = sealed_for_qtc(W, max(0.707, W.Qts * math.sqrt(2)), n), qb3(W, n)
    if align == "auto":
        f3s = sealed_metrics(W, sv["Vb_L"], n)["f3"] if sv["Vb_L"] else 1e9
        align = "vented" if W.Qts <= 0.5 and optimise_vented(W, vv["Vb_L"], n)["f3"] < f3s - 5 else "sealed"
    net = (vv["Vb_L"] if align == "vented" else (sv["Vb_L"] or (W.Vas_L or 20.0) * n * 0.5))
    min_in = W.outer_d_mm + 2 * MARGIN + 6
    stack = n * (W.outer_d_mm + GAP) + 2 * MARGIN
    design: dict[str, Any] = {}
    loc = req.get("port_location", "front")
    gross = net * 1.1
    for _ in range(7):
        w, dp, h = _solve_dims(gross, min_in, max(min_in, stack), req.get("fixed") or {}, t)
        cab = {"mode": "free", "outer_w": w + 2 * t, "outer_h": h + 2 * t, "outer_d": dp + 2 * t, "wall_t": t, "baffle_t": t,
               "fill": 0.5 if align == "vented" else 0.8, "bracing_pct": 3.0}
        sub_cfg: dict[str, Any] = dict(DEFAULT_SUB["sub"])  # type: ignore[arg-type]
        sub_cfg.update(req.get("sub") or {})
        design = {"cabinet": cab, "drivers": {"woofer": {"id": W.id, "count": n}},
                  "box": {"type": align, "port": {"location": loc}}, "sub": sub_cfg}
        r = simulate_sub(design)
        if loc == "front" and any("No free space for the" in w for w in r["warnings"]):
            loc = "rear"  # crowded baffle: port on the back panel
            continue
        gross += net - r["metrics"]["net_volume_L"]
    return {"alignment": align, "result": simulate_sub(design)}
