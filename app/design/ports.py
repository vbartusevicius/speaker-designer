"""Port sizing, air-speed verification, placement, and option comparison."""
from __future__ import annotations

import math
from typing import Any

import numpy as np

from ..physics.constants import PORT_VELOCITY_LIMIT, PORT_VELOCITY_LIMIT_FLARED
from ..physics.enclosure import Box, freq_axis, simulate
from ..physics.port import FLARED_KITS, STANDARD_TUBES, acoustic_length_mm, eq_diameter_mm, pipe_resonance_hz, port_length_mm


def design_port(woofer, n: int, g, net_L: float, fb: float, cfg: dict,
                design_power_w: float, fill: float, return_all: bool = False):
    loc = cfg.get("location", "front")
    flared = bool(cfg.get("flared"))
    limit = PORT_VELOCITY_LIMIT_FLARED if flared else PORT_VELOCITY_LIMIT
    wall = float(cfg.get("wall_mm", 3.0))
    shape = cfg.get("shape", "round")
    vb_eff = net_L * (1 + 0.2 * fill)
    f = freq_axis(10, 400, 160)
    v_design = math.sqrt(design_power_w * (woofer.Re / n))
    space = {"front": g.int_d, "rear": g.int_d, "bottom": g.int_h}.get(loc, g.int_d)
    cands = []
    counts: list[int] = [int(cfg["count"])] if cfg.get("count") else [1, 2]
    geo: list[tuple[int, float, float, float, dict | None]]
    h = float(cfg.get("slot_h_mm", 40.0))
    if shape == "slot":
        widths = [float(cfg["slot_w_mm"])] if cfg.get("slot_w_mm") else [float(w) for w in range(60, int(g.int_w - 40), 10)]
        geo = [(1, w * h / 100.0, h, w, None) for w in widths]
    else:
        tubes: list[dict] = list(FLARED_KITS if flared else STANDARD_TUBES)
        if cfg.get("d_mm"):
            d_req = float(cfg["d_mm"])
            tubes = [t for t in tubes if abs(float(t["id"]) - d_req) < 1.5] or [
                {"name": f"Tube ID {d_req:.0f} mm", "id": d_req, "od": d_req + 2 * wall}]
        geo = [(c, c * math.pi * (float(t["id"]) / 2) ** 2 / 100.0, float(t["id"]), float(t["id"]), t)
               for c in counts for t in tubes]
    for count, area, d1, d2, tube in geo:
        d_eq = eq_diameter_mm(area / count)
        k = 0.85 if shape == "slot" else 0.732
        L = port_length_mm(vb_eff, fb, area, count, k)
        L_phys = max(L, g.baffle_t)
        leff = acoustic_length_mm(L_phys, area, count, k)
        box = Box("vented", net_L, fb, area, leff, fill=fill)
        sim = simulate(woofer, box, f, vin=v_design, n=n, use_le=False, breakup=False)
        band = (f > 0.5 * fb) & (f < 3 * fb)
        assert sim.port_vel_peak is not None
        vel = float(np.max(sim.port_vel_peak[band]))
        max_len = space - max(d_eq, 50.0) if shape != "slot" else space - h
        fits = L_phys <= max_len
        cands.append({"location": loc, "shape": shape, "count": count, "d_mm": round(d1, 1),
                      "slot_w_mm": round(d2, 1) if shape == "slot" else None,
                      "slot_h_mm": round(d1, 1) if shape == "slot" else None,
                      "area_cm2": round(area, 2), "d_eq_mm": round(d_eq, 1), "length_mm": round(L_phys, 1),
                      "leff_mm": round(leff, 1), "max_len_mm": round(max_len, 1), "fits": fits,
                      "vel_peak_ms": round(vel, 2), "vel_limit_ms": limit, "flared": flared,
                      "outer_d_mm": (tube["od"] if tube else round(d1 + 2 * wall, 1)) if shape != "slot" else None,
                      "tube_name": tube["name"] if tube else None,
                      "flange_mm": 15.0 if flared else 0.0,
                      "pipe_resonance_hz": round(pipe_resonance_hz(leff), 0),
                      "ext_volume_L": round((math.pi * ((tube["od"] if tube else d1 + 2 * wall) / 2) ** 2 * L_phys * count if shape != "slot"
                                             else d2 * (d1 + 18) * L_phys) * 1e-6, 2),
                      "too_short": L < g.baffle_t})
    if return_all:
        return cands
    comfy = [c for c in cands if c["fits"] and c["vel_peak_ms"] <= 0.7 * limit]  # quiet: <= ~12 m/s straight
    good = [c for c in cands if c["fits"] and c["vel_peak_ms"] <= limit]
    if comfy:
        return min(comfy, key=lambda c: (c["count"], c["area_cm2"]))
    if good:
        return min(good, key=lambda c: c["vel_peak_ms"])
    fit = [c for c in cands if c["fits"]]
    return min(fit, key=lambda c: c["vel_peak_ms"]) if fit else min(cands, key=lambda c: c["length_mm"] - c["max_len_mm"])


def best_auto_port(woofer, n: int, g, net_L: float, fb: float, cfg: dict, design_power_w: float, fill: float) -> dict:
    """Compare round pipe, flared kit, and slot when port shape is 'auto'."""
    if cfg.get("shape", "round") != "auto":
        return design_port(woofer, n, g, net_L, fb, cfg, design_power_w, fill)
    opts = [design_port(woofer, n, g, net_L, fb, {**cfg, **o}, design_power_w, fill)
            for o in ({"shape": "round", "flared": False}, {"shape": "round", "flared": True}, {"shape": "slot"})]
    ok = [o for o in opts if o["fits"]] or opts
    return min(ok, key=lambda o: o["vel_peak_ms"] / o["vel_limit_ms"])


def bottom_port_positions(g, pos: dict, W, M, chamber: dict | None, port: dict) -> list[dict]:
    """Positions (interior plan coords: x across width, z depth from baffle) for vertical bottom ports."""
    R = (port["outer_d_mm"] or port["d_eq_mm"]) / 2 + 2
    tube_top = port["length_mm"]
    blockers = []
    for p in pos.get("woofer", []):
        r = W.cutout_d_mm / 2
        if tube_top > p["y"] - g.open_y - r:
            blockers.append((p["x"] - g.open_x - r, p["x"] - g.open_x + r, 0, W.depth_mm + 5))
    if M is not None and pos.get("mid"):
        hw = (chamber["ext_w"] if chamber else M.cutout_d_mm) / 2
        hh = (chamber["ext_h"] if chamber else M.cutout_d_mm) / 2
        cx = pos["mid"]["x"] - g.open_x + (chamber["offset_x"] if chamber else 0)
        cy = pos["mid"]["y"] - g.open_y + (chamber["offset_y"] if chamber else 0)
        dep = chamber["ext_depth"] if chamber else M.depth_mm
        if tube_top > cy - hh:
            blockers.append((cx - hw, cx + hw, 0, dep + 5))
    out: list[dict[str, Any]] = []
    for _ in range(port["count"]):
        best = None
        for z in np.arange(R + 10, g.int_d - R - 10, 5):
            for x in np.arange(R + 10, g.int_w - R - 10, 5):
                if any(x + R > x0 and x - R < x1 and z + R > z0 and z - R < z1 for x0, x1, z0, z1 in blockers):
                    continue
                if any(math.hypot(x - o["x"], z - o["z"]) < 2 * R + 10 for o in out):
                    continue
                score = x + 0.3 * abs(z - g.int_d / 2)
                if best is None or score < best[0]:
                    best = (score, float(x), float(z))
        if best is None:
            break
        out.append({"x": best[1], "z": best[2], "plan": True})
    return out


def port_options(design: dict) -> list[dict]:
    """Every port that could tune this box: straight HT pipes (1-2), flared kits, slots - with fit and air speed."""
    from .system import resolve
    ctx = resolve(design)
    d, W, g = ctx.design, ctx.W, ctx.g
    if not ctx.port:
        return []
    fb, net = d["box"]["fb"], ctx.box.Vb_L
    out = []
    for cfg in ({"shape": "round", "flared": False}, {"shape": "round", "flared": True}, {"shape": "slot"}):
        base = {**d["box"]["port"], **cfg, "d_mm": None, "count": None, "slot_w_mm": None}
        out += design_port(W, ctx.n, g, net, fb, base, d["sim"]["design_power_w"], g.fill, return_all=True)
    return sorted((c for c in out if c["fits"] and not c["too_short"]), key=lambda c: c["vel_peak_ms"])[:12]
