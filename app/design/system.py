"""Full-system design resolver + simulator (decomposed into focused steps using ResolvedContext)."""
from __future__ import annotations

import json
import math
from typing import Any

import numpy as np

from ..physics import crossover as xo
from ..physics.alignments import choose_box_alignment, optimise_vented, sealed_metrics
from ..physics.baffle import baffle_step_f3, diffraction
from ..physics.constants import C, PORT_VELOCITY_LIMIT, PORT_VELOCITY_LIMIT_FLARED
from ..physics.enclosure import Box, bass_metrics, freq_axis, group_delay_ms, simulate, simulate_closed
from . import drivers_db
from . import measurements as meas
from .cabinet import DEFAULT_FIT, chamber_for, damping_plan, geometry, volume_budget
from .layout import auto_layout, chamber_collisions, clearances, place_front_ports, repair_chamber, validate_layout
from .models import ResolvedContext
from .ports import bottom_port_positions, design_port
from .utils import band_median, deep_merge, mag_db, round_nested, smooth_db, spl_db

DEFAULT_DESIGN: dict[str, Any] = {
    "name": "Living-room 3-way",
    "cabinet": DEFAULT_FIT,
    "drivers": {"woofer": {"id": "sb-sb23nrxs45-8", "count": 1}, "mid": {"id": "sb-sb15mfc30-8"},
                "tweeter": {"id": "sb-sb26adc-c000-4"}},
    "box": {"type": "auto", "fb": None,
            "port": {"location": "front", "shape": "round", "d_mm": None, "count": None, "flared": False,
                     "wall_mm": 3.0, "slot_h_mm": 40.0}},
    "layout": {"style": "auto", "positions": None, "side": "left", "min_web_mm": 10.0},
    "crossover": {"mode": "active", "kind": None, "f_wm": None, "f_mt": None, "levels": None,
                  "polarity": None, "zobel": True, "tweeter_protect": True},
    "sim": {"distance_mm": 2000.0, "vin": 2.83, "edge_radius_mm": 0.0, "design_power_w": 25.0,
            "baffle_extend_mm": {"left": 0.0, "right": 0.0, "top": 0.0, "bottom": 0.0},
            "listen_y_mm": None, "fmin": 10.0, "fmax": 20000.0, "points": 360},
}


def choose_crossovers(W, M, T, mid_fc: float | None, mode: str) -> dict[str, Any]:
    k_tw = 2.5 if mode == "active" else 3.0
    out: dict[str, Any] = {"notes": []}
    beam_w = C / (math.pi * 2 * W.piston_radius)
    if M is None:
        lo = max(T.Fs * k_tw, T.fmin)
        hi = min(W.fmax / 1.5, beam_w * 2.0)
        out["f_wt"] = round(math.sqrt(lo * hi) if lo <= hi else lo, -1)
        if lo > hi:
            out["notes"].append("2-way: woofer cannot reach the tweeter's lowest safe crossover")
        return out
    beam_m = C / (math.pi * 2 * M.piston_radius)
    lo = max(mid_fc * 2.5 if mid_fc else 0, M.fmin, 200.0)
    hi = min(W.fmax / 3.0, beam_w * 1.2, 800.0)
    out["f_wm"] = round(math.sqrt(lo * hi) if lo <= hi else lo, -1)
    if lo > hi:
        out["notes"].append(f"woofer-mid: mid needs >= {lo:.0f} Hz but woofer should stop by {hi:.0f} Hz")
    lo2 = max(T.Fs * k_tw, T.fmin, 1500.0)
    hi2 = min(M.fmax / 1.5, beam_m * 2.5, 5000.0)
    out["f_mt"] = round(math.sqrt(lo2 * hi2) if lo2 <= hi2 else lo2, -1)
    if lo2 > hi2:
        out["notes"].append(f"mid-tweeter: tweeter needs >= {lo2:.0f} Hz but mid should stop by {hi2:.0f} Hz")
    return out


def positions_key(pos) -> str:
    return json.dumps({k: v for k, v in (pos or {}).items() if k != "port"}, sort_keys=True)


def bem_request(design: dict[str, Any]) -> dict[str, Any]:
    """Cabinet + pistons for the BEM service (metres), taken from the resolved design."""
    r = simulate_design({**design, "sim": {**(design.get("sim") or {}), "bem": None, "points": 120}})
    g, pos, d = r["geometry"], r["design"]["layout"]["positions"], r["drivers"]
    pc = lambda name, p, drv: {"name": name, "x": p["x"] / 1000, "y": p["y"] / 1000, "r": math.sqrt(drv["Sd_cm2"] * 1e-4 / math.pi)}
    pistons = [pc(f"woofer{i + 1}", p, d["woofer"]) for i, p in enumerate(pos["woofer"])]
    if d["mid"]:
        pistons.append(pc("mid", pos["mid"], d["mid"]))
    pistons.append(pc("tweeter", pos["tweeter"], d["tweeter"]))
    depth = g["int_d"] + g["back_t"] + g["baffle_t"]
    lst = r["design"]["sim"]
    return {"box": {"w": g["baffle_w"] / 1000, "h": g["baffle_h"] / 1000, "d": depth / 1000}, "pistons": pistons,
            "freqs": [round(float(x), 1) for x in np.geomspace(80, 1200, 8)],
            "listener": {"x": pos["tweeter"]["x"] / 1000, "y": (lst.get("listen_y_mm") or pos["tweeter"]["y"]) / 1000, "dist": lst["distance_mm"] / 1000},
            "positions_key": positions_key(pos)}


def _network_for(r: dict[str, Any]) -> dict[str, Any]:
    return r.get("_networks") or {}


def _resolve_box_and_port(d: dict[str, Any], W, n: int, M, T, g, chamber, pre: dict[str, Any],
                          warnings: list[str]) -> tuple[Box, dict | None, dict, dict, dict]:
    net, fill, bx = pre["net_L"], g.fill, d["box"]
    btype, sealed, vent = choose_box_alignment(W, net, n, fill, bx["type"])
    if btype != "vented":
        bx["type"], bx["fb"] = btype, None
        return Box("sealed", net, fill=max(fill, 0.6)), None, pre, {"sealed": sealed, "vented": vent}, bx

    fb = float(bx.get("fb") or vent["fb"])
    port = design_port(W, n, g, net, fb, bx["port"], d["sim"]["design_power_w"], fill)
    net = volume_budget(g, W, n, M, T, chamber, port["ext_volume_L"])["net_L"]
    if not bx.get("fb"):
        fb = optimise_vented(W, net, n, fill=fill)["fb"]
    port_cfg = {
        **bx["port"],
        "d_mm": bx["port"].get("d_mm") or (port["d_mm"] if port["shape"] != "slot" else None),
        "count": port["count"],
        "slot_w_mm": port.get("slot_w_mm"),
    }
    port = design_port(W, n, g, net, fb, port_cfg, d["sim"]["design_power_w"], fill)
    vols = volume_budget(g, W, n, M, T, chamber, port["ext_volume_L"])
    if not port["fits"]:
        warnings.append(f"Port {port['length_mm']:.0f} mm is longer than the {port['max_len_mm']:.0f} mm available "
                        f"({port['location']}): use an L-shaped/bent port, a slot, or a lower port area.")
    if port["vel_peak_ms"] > port["vel_limit_ms"]:
        warnings.append(f"Port air speed {port['vel_peak_ms']:.1f} m/s at {d['sim']['design_power_w']:.0f} W "
                        f"exceeds {port['vel_limit_ms']:.0f} m/s - audible chuffing likely; use larger/flared ports.")
    if port["too_short"]:
        warnings.append("Required port is shorter than the baffle: it becomes a plain hole; reduce area.")
    bx["type"], bx["fb"] = btype, round(fb, 1)
    return Box("vented", net, fb, port["area_cm2"], port["leff_mm"], fill=fill), port, vols, {"sealed": sealed, "vented": vent}, bx


def _place_ports(g, pos: dict, W, M, T, chamber, port: dict | None, min_web: float, warnings: list[str]) -> None:
    if port and port["location"] in ("front", "rear") and port["shape"] == "round":
        if len(pos.get("port", [])) != port["count"]:
            occ = pos if port["location"] == "front" else {"woofer": [], "tweeter": None}
            pos["port"] = place_front_ports(g, occ, W, M, T, port, port["count"], "left", min_web)
            if len(pos["port"]) < port["count"]:
                warnings.append(f"No free space for the {port['location']} port(s): use a slot, bottom or rear port.")
    elif port and port["location"] == "bottom":
        pos["port"] = bottom_port_positions(g, pos, W, M, chamber, port)
    else:
        pos.pop("port", None)


def _resolve_crossovers(xc: dict[str, Any], W, M, T, chamber, warnings: list[str], notes: list[str]) -> float | None:
    mode = xc["mode"]
    kind = xc.get("kind") or ("LR4" if mode == "active" else "LR2")
    if mode == "passive" and kind == "LR4":
        kind = "LR2"
    xc["kind"] = kind
    mid_fc = sealed_metrics(M, chamber["Vb_L"], 1, fill=0.8)["fc"] if chamber else (M.Fs if M else None)
    auto_xo = choose_crossovers(W, M, T, mid_fc, mode)
    notes += auto_xo["notes"]
    if M is None:
        xc["f_wm"] = None
        xc["f_mt"] = float(xc.get("f_mt") or auto_xo["f_wt"])
    else:
        xc["f_wm"] = float(xc.get("f_wm") or auto_xo["f_wm"])
        xc["f_mt"] = float(xc.get("f_mt") or auto_xo["f_mt"])
    if xc["f_mt"] < T.Fs * (2.2 if mode == "active" else 2.8):
        warnings.append(f"Tweeter crossover {xc['f_mt']:.0f} Hz is close to its Fs ({T.Fs:.0f} Hz) - risk of overload.")
    return mid_fc


def resolve(design: dict[str, Any]) -> ResolvedContext:
    """Fill every automatic choice and return a typed ResolvedContext."""
    d = deep_merge(DEFAULT_DESIGN, design)
    warnings: list[str] = []
    notes: list[str] = []
    dv = d["drivers"]
    W = drivers_db.get(dv["woofer"]["id"])
    n = int(dv["woofer"].get("count") or 1)
    M = drivers_db.get((dv.get("mid") or {}).get("id"))
    T = drivers_db.get(dv["tweeter"]["id"])
    assert W is not None and T is not None

    g = geometry(d["cabinet"])
    if g.back_mode == "keep":
        warnings.append("A thin back panel is not airtight or rigid: replace it or add 18 mm MDF inside.")

    lay = d["layout"]
    pos = lay.get("positions")
    auto_placed = not pos
    min_web = float(lay.get("min_web_mm") or 10)
    if not pos:
        al = auto_layout(g, W, n, M, T, lay.get("style", "auto"), "left", min_web)
        pos = al["positions"]
        if pos is None:
            raise ValueError("Drivers do not fit on the baffle: " + "; ".join(i["msg"] for i in al["issues"]))
        lay["style"] = al["style"]
    chamber = chamber_for(g, pos, W, M, T)
    if chamber and auto_placed:
        pos, chamber = repair_chamber(g, pos, W, M, T, chamber, lay.get("style"))
    pre = volume_budget(g, W, n, M, T, chamber)

    box, port, vols, alignments, _ = _resolve_box_and_port(d, W, n, M, T, g, chamber, pre, warnings)
    _place_ports(g, pos, W, M, T, chamber, port, min_web, warnings)

    front_port = port if port and port["location"] == "front" and port["shape"] == "round" else None
    layout_issues = validate_layout(g, pos, W, M, T, front_port, min_web) + chamber_collisions(g, pos, W, T, chamber, port)
    warnings += [i["msg"] for i in layout_issues if i["level"] in ("error", "warn")]
    clear = clearances(g, pos, W, M, T, front_port)
    lay["positions"] = pos

    if W.depth_mm + 10 > g.int_d:
        warnings.append(f"Woofer depth {W.depth_mm:.0f} mm does not fit {g.int_d:.0f} mm internal depth.")
    if chamber and chamber["depth_mode_hz"] < 1500:
        notes.append(f"Mid chamber standing wave (~{chamber['depth_mode_hz']:.0f} Hz from the {chamber['inner_depth']:.0f} mm box depth): "
                     "pack the chamber loosely with wool or polyester wadding so internal reflections do not colour the midrange.")
    if chamber and chamber["ext_depth"] > g.int_d - 10:
        warnings.append("Mid chamber is deeper than the cabinet; use a wider chamber or a tube.")
    rebate_left = g.baffle_t - max(W.flange_mm, (M.flange_mm if M else 0))
    if rebate_left < 8:
        warnings.append(f"Flush-mount rebates leave only {rebate_left:.1f} mm of baffle; consider a 2nd baffle layer or surface mount.")

    mid_fc = _resolve_crossovers(d["crossover"], W, M, T, chamber, warnings, notes)
    return ResolvedContext(
        design=d, W=W, n=n, M=M, T=T, g=g, chamber=chamber, volumes=vols, box=box, port=port,
        alignments=alignments, mid_fc=mid_fc, clearances=clear, layout_issues=layout_issues,
        warnings=warnings, notes=notes,
    )


def _apply_measurements(d: dict[str, Any], box: Box, f: np.ndarray, vin: float,
                        driver_sims: tuple[tuple[str, Any, Any], ...]) -> dict[str, list[str]]:
    measured: dict[str, list[str]] = {}
    n = int(d["drivers"]["woofer"].get("count") or 1)
    for role, drv, sim in driver_sims:
        if drv is None or sim is None:
            continue
        frd, zma = meas.load(drv.id, "frd"), meas.load(drv.id, "zma")
        used: list[str] = []
        if frd:
            p_m = meas.response(frd, f, vin)
            if role == "woofer":
                p_m = meas.merge_low(sim.p, p_m * n, f, max(200.0, 3 * (box.fb or 0)))
            sim.p = p_m
            used.append("response")
        if zma:
            z_m = meas.impedance(zma, f)
            if role == "woofer":
                z_m = z_m / n if d["drivers"]["woofer"].get("wiring", "parallel") == "parallel" else z_m * n
                t = np.clip(np.log2(f / 140.0), 0, 1)
                z_m = sim.zin * (1 - t) + z_m * t
            sim.zin = z_m
            used.append("impedance")
        if used:
            measured[role] = used
    return measured


def _build_networks(ways: list[dict[str, Any]], xc: dict[str, Any], f: np.ndarray, n: int,
                    f_lo_x: float) -> tuple[dict[str, Any], dict[str, Any]]:
    parts: dict[str, Any] = {}
    networks: dict[str, Any] = {}
    for w in ways:
        lo, hi = (
            (None, f_lo_x) if w["role"] == "woofer"
            else (xc["f_wm"], xc["f_mt"]) if w["role"] == "mid"
            else (xc["f_mt"], None)
        )
        if xc["mode"] == "active":
            lp, hp = xo.FILTERS[xc["kind"]]
            h = np.ones_like(f, dtype=complex)
            if lo:
                h *= hp(f, lo)
            if hi:
                h *= lp(f, hi)
            w["H"], w["zsys"] = h * 10 ** (-w["atten"] / 20), w["sim"].zin
            if w["role"] == "tweeter" and xc.get("tweeter_protect", True):
                cp = xo.protection_cap(xc["f_mt"], 1.1 * w["sim"].re_total)
                hp_, zp_ = xo.ladder([("series", "C", cp)], w["sim"].zin, f)
                w["H"], w["zsys"] = w["H"] * hp_, zp_
                pt = xo._part("C1", "C", cp, "series, in the tweeter + lead", "tweeter")
                parts["tweeter"] = {
                    "R_design_ohm": None, "parts": [pt],
                    "schematic": [{"pos": "series", "kind": "C", "label": f"C1 {pt['build']}", "note": "protection"}],
                    "purpose": f"DC / turn-on-thump protection; adds a gentle 6 dB/oct roll-off below ~{1 / (2 * math.pi * cp * 1.1 * w['sim'].re_total):.0f} Hz (included in the simulation).",
                }
        else:
            if w["atten"] < 1.0:
                w["atten"] = 0.0
            drv, re_tot = w["drv"], w["sim"].re_total
            use_z = xc.get("zobel", True) and w["role"] != "tweeter" and drv.Le_mH > 0.1
            r_design = 1.1 * re_tot if use_z else float(np.abs(np.interp(float(lo or hi or 1000.0), f, np.abs(w["sim"].zin))))
            br = xo.build_passive(w["role"], lo, hi, r_design, re_tot, drv.Le_mH / (n if w["role"] == "woofer" else 1),
                                  w["atten"], xc["kind"], use_z)
            h, zin = xo.ladder(br["network"], w["sim"].zin, f)
            networks[w["role"]] = br["network"]
            w["H"], w["zsys"] = h, zin
            parts[w["role"]] = {"R_design_ohm": round(r_design, 2), "parts": br["parts"], "schematic": br["schematic"]}
    return parts, networks


def simulate_design(design: dict[str, Any]) -> dict[str, Any]:
    ctx = resolve(design)
    d, W, n, M, T, g, box = ctx.design, ctx.W, ctx.n, ctx.M, ctx.T, ctx.g, ctx.box
    s, xc = d["sim"], d["crossover"]
    f = freq_axis(s["fmin"], s["fmax"], int(s["points"]))
    vin = float(s["vin"])
    warnings = list(ctx.warnings)

    sw = simulate(W, box, f, vin, n)
    sm = simulate(M, Box("sealed", ctx.chamber["Vb_L"], fill=0.8), f, vin) if (M and ctx.chamber) else (
        simulate_closed(M, f, vin) if M else None)
    st = simulate_closed(T, f, vin)
    measured = _apply_measurements(d, box, f, vin, (("woofer", W, sw), ("mid", M, sm), ("tweeter", T, st)))

    pos = d["layout"]["positions"]
    ext = s["baffle_extend_mm"]
    poly = [[-ext["left"], -ext["bottom"]], [g.baffle_w + ext["right"], -ext["bottom"]],
            [g.baffle_w + ext["right"], g.baffle_h + ext["top"]], [-ext["left"], g.baffle_h + ext["top"]]]
    lx = pos["tweeter"]["x"]
    ly = s["listen_y_mm"] if s.get("listen_y_mm") is not None else pos["tweeter"]["y"]
    R = float(s["distance_mm"])
    k = 2 * math.pi * f / C
    bem: dict[str, Any] | None = s.get("bem") if isinstance(s.get("bem"), dict) else None
    bem_used = bool(bem and bem.get("positions_key") == positions_key(pos))

    def acoustic(drv, places, z_off, names):
        tot = np.zeros_like(f, dtype=complex)
        dif = np.zeros_like(f, dtype=complex)
        for i, p in enumerate(places):
            D = diffraction(f, g.baffle_w, g.baffle_h, p["x"], p["y"], drv.piston_radius, (lx, ly, R),
                            s["edge_radius_mm"], polygon=poly)
            if bem_used and bem is not None and (b := bem["pistons"].get(names[i])):
                bf = np.array(bem["freqs"])
                tr = np.array(b["re"]) + 1j * np.array(b["im"])
                lf, lb = np.log(f), np.log(bf)
                Db = np.interp(lf, lb, np.abs(tr)) * np.exp(1j * np.interp(lf, lb, np.unwrap(np.angle(tr))))
                t = np.clip((f - 0.75 * bf[-1]) / (0.25 * bf[-1]), 0, 1)
                D = Db * (1 - t) + D * t
            L0 = math.sqrt((p["x"] - lx) ** 2 + (p["y"] - ly) ** 2 + (R + z_off) ** 2)
            tot += D * (R / L0) * np.exp(-1j * k * (L0 - R) / 1000.0) * (1000.0 / R)
            dif += D
        return tot / len(places), dif / len(places)

    aw, dw = acoustic(W, pos["woofer"], 0.33 * W.depth_mm, [f"woofer{i + 1}" for i in range(len(pos["woofer"]))])
    ways = [{"role": "woofer", "drv": W, "sim": sw, "a": sw.p_per_volt * aw, "dif": dw}]
    if M and sm is not None:
        am, dm = acoustic(M, [pos["mid"]], 0.33 * M.depth_mm, ["mid"])
        ways.append({"role": "mid", "drv": M, "sim": sm, "a": sm.p_per_volt * am, "dif": dm})
    at_, dt = acoustic(T, [pos["tweeter"]], 0.0, ["tweeter"])
    ways.append({"role": "tweeter", "drv": T, "sim": st, "a": st.p_per_volt * at_, "dif": dt})

    bm = bass_metrics(sw, W)
    f_lo_x = xc["f_wm"] if M else xc["f_mt"]
    bands = {"woofer": (max(80.0, 2 * bm["f3"]), f_lo_x / 1.3), "tweeter": (xc["f_mt"] * 1.5, 10000.0)}
    if M:
        bands["mid"] = (xc["f_wm"] * 1.3, xc["f_mt"] / 1.3)
    for w in ways:
        w["level"] = band_median(f, spl_db(w["a"] * vin), *bands[w["role"]])
    target = min(w["level"] for w in ways)
    user_lv = xc.get("levels") or {}
    for w in ways:
        w["atten"] = float(user_lv.get(w["role"], round(w["level"] - target, 1)))

    parts, networks = _build_networks(ways, xc, f, n, f_lo_x)
    pol_cfg = xc.get("polarity") or {}
    choices_m = [pol_cfg["mid"]] if "mid" in pol_cfg else ([1, -1] if M else [1])
    choices_t = [pol_cfg["tweeter"]] if "tweeter" in pol_cfg else [1, -1]
    m_band = (f >= 150) & (f <= 10000)
    combos = []
    for pm in choices_m:
        for pt in choices_t:
            tot = sum(w["a"] * vin * w["H"] * (1 if w["role"] == "woofer" else pm if w["role"] == "mid" else pt) for w in ways)
            combos.append((float(np.std(smooth_db(f[m_band], spl_db(tot[m_band]), 6))), pm, pt, tot))
    _, pm, pt, total = min(combos, key=lambda c: c[0])
    pol = {"woofer": 1, "mid": pm, "tweeter": pt} if M else {"woofer": 1, "tweeter": pt}
    xc["polarity"], xc["levels"] = pol, {w["role"]: w["atten"] for w in ways}
    zsys = 1 / sum(1 / w["zsys"] for w in ways) if xc["mode"] == "passive" else None

    v_design = math.sqrt(float(s["design_power_w"]) * sw.re_total)
    mx = sw.max_spl(PORT_VELOCITY_LIMIT_FLARED if (ctx.port and ctx.port["flared"]) else PORT_VELOCITY_LIMIT)
    hw = ways[0]["H"]
    curves = {
        "f": f.tolist(), "spl": {w["role"]: spl_db(w["a"] * vin * w["H"] * pol[w["role"]]).tolist() for w in ways},
        "spl_raw": {w["role"]: spl_db(w["a"] * vin).tolist() for w in ways}, "sum": spl_db(total).tolist(),
        "sum_1m_re": (total * R / 1000.0).real.tolist(), "sum_1m_im": (total * R / 1000.0).imag.tolist(),
        "sum_smoothed": smooth_db(f, spl_db(total), 6).tolist(), "phase_sum": np.degrees(np.angle(total)).tolist(),
        "group_delay_sum_ms": np.clip(group_delay_ms(f, total), -50, 200).tolist(),
        "group_delay_box_ms": np.clip(sw.group_delay_ms(), -50, 200).tolist(), "box_spl_halfspace": sw.spl.tolist(),
        "diffraction_db": {w["role"]: mag_db(w["dif"]).tolist() for w in ways},
        "impedance": {w["role"]: np.abs(w["sim"].zin).tolist() for w in ways},
        "impedance_phase": {w["role"]: np.degrees(np.angle(w["sim"].zin)).tolist() for w in ways},
        "impedance_system": None if zsys is None else np.abs(zsys).tolist(),
        "impedance_system_phase": None if zsys is None else np.degrees(np.angle(zsys)).tolist(),
        "excursion_mm": (sw.x_peak_mm * v_design / vin).tolist(),
        "excursion_filtered_mm": (sw.x_peak_mm * v_design / vin * np.abs(hw)).tolist(),
        "xmax_mm": W.Xmax_mm, "port_velocity_ms": None if sw.port_vel_peak is None else (sw.port_vel_peak * v_design / vin).tolist(),
        "max_spl": mx["spl"].tolist(), "max_spl_limit": mx["limit"].tolist(), "design_power_w": s["design_power_w"],
    }
    if M and sm is not None:
        xm = sm.x_peak_mm * math.sqrt(float(s["design_power_w"]) * sm.re_total) / vin * np.abs(ways[1]["H"])
        curves["mid_excursion_mm"] = xm.tolist()
        if float(np.max(xm[f > 0.7 * xc["f_wm"]])) > M.Xmax_mm:
            warnings.append(f"Midrange exceeds Xmax at {s['design_power_w']:.0f} W near the woofer crossover; raise f_wm.")

    tot_db = spl_db(total)
    sens = band_median(f, tot_db, 300, 3000)
    sm6 = smooth_db(f[m_band], tot_db[m_band], 6)
    sys_ref = band_median(f, tot_db, 200, 2000)
    sys_f3 = next((float(f[i]) for i in np.where(f < 200)[0][::-1] if tot_db[i] < sys_ref - 3), None)
    zmin = float(np.min(np.abs(zsys)[(f > 20) & (f < 20000)])) if zsys is not None else None
    if zmin is not None and zmin < 3.2:
        warnings.append(f"System impedance dips to {zmin:.1f} ohm - make sure the amplifier is 4-ohm stable.")

    at = lambda arr, hz: float(np.interp(math.log(hz), np.log(f), arr))
    price_each = W.price_eur * n + (M.price_eur if M else 0) + T.price_eur
    for role, b in parts.items():
        b["polarity"] = pol.get(role, 1)
    solder = xo.soldering_guide(xc["mode"], parts)
    xo_cost = round(sum(p["est_eur"] for b in parts.values() for p in b["parts"]) + (12.0 if xc["mode"] == "passive" else 0.0), 2)
    metrics = {
        "ways": 3 if M else 2, "box_type": box.kind, "net_volume_L": round(box.Vb_L, 2),
        "fb_hz": None if box.fb is None else round(box.fb, 1),
        "qtc": round(ctx.alignments["sealed"]["qtc"], 3) if box.kind == "sealed" else None,
        "woofer_f3_hz": round(bm["f3"], 1), "woofer_f6_hz": round(bm["f6"], 1), "woofer_f10_hz": round(bm["f10"], 1),
        "woofer_peak_db": round(bm["peak_db"], 2), "system_f3_hz": None if sys_f3 is None else round(sys_f3, 1),
        "sensitivity_db_2v83_at_distance": round(sens, 1), "sensitivity_db_2v83_1m": round(sens + 20 * math.log10(R / 1000.0), 1),
        "deviation_db": round(float((sm6.max() - sm6.min()) / 2), 2),
        "max_spl_40hz": round(at(mx["spl"], 40), 1), "max_spl_63hz": round(at(mx["spl"], 63), 1), "max_spl_100hz": round(at(mx["spl"], 100), 1),
        "port_velocity_peak_ms": ctx.port["vel_peak_ms"] if ctx.port else None,
        "z_min_ohm": None if zmin is None else round(zmin, 2),
        "baffle_step_f3_hz": round(baffle_step_f3(g.baffle_w + ext["left"] + ext["right"]), 0),
        "price_drivers_each_eur": round(price_each, 0), "price_drivers_pair_eur": round(2 * price_each, 0),
        "levels_db": {w["role"]: round(w["level"], 1) for w in ways},
        "mid_chamber_fc_hz": None if ctx.mid_fc is None else round(ctx.mid_fc, 1),
        "crossover_parts_eur_each": xo_cost,
    }
    return {"design": d, "geometry": g.to_dict(), "volumes": ctx.volumes, "chamber": ctx.chamber,
            "damping": damping_plan(box.kind == "vented", ctx.port, bool(ctx.chamber)),
            "clearances": ctx.clearances, "soldering": solder, "measured": measured, "_networks": networks,
            "bem": {"used": bem_used, "stale": bool(bem) and not bem_used, "f_max": bem["freqs"][-1] if bem is not None else None,
                    "polar": bem["pistons"] if bem is not None and bem_used else None, "freqs": bem["freqs"] if bem is not None and bem_used else None,
                    "angles": bem.get("angles") if bem is not None and bem_used else None},
            "port": ctx.port, "alignments": round_nested(ctx.alignments), "curves": curves, "metrics": metrics,
            "crossover_parts": parts, "warnings": warnings, "notes": ctx.notes,
            "drivers": {"woofer": W.to_dict(), "mid": M.to_dict() if M else None, "tweeter": T.to_dict()},
            "layout_issues": ctx.layout_issues}
