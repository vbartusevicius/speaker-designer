"""Driver selection for a given cabinet + budget (fit mode), and box-from-drivers (reverse mode)."""
from __future__ import annotations

import math

from ..physics.alignments import optimise_vented, qb3, sealed_for_qtc, sealed_metrics
from . import drivers_db
from .cabinet import geometry, mid_chamber, mid_chamber_volume_target, volume_budget
from .layout import auto_layout
from .system import DEFAULT_DESIGN, choose_crossovers, simulate_design
from .utils import deep_merge

DEFAULT_PRIORITIES = {"bass": 1.0, "output": 0.7, "accuracy": 1.0, "quality": 0.8, "value": 0.4}


def _clamp(x, lo=0.0, hi=1.0):
    return max(lo, min(hi, x))


def optimise(req: dict) -> dict:
    cab = req.get("cabinet") or {}
    g = geometry(cab)
    budget = float(req.get("budget_eur_pair", 600))
    ways = req.get("ways", "3")
    mode = req.get("crossover_mode", "active")
    box_pref = req.get("box", "auto")
    port_loc = req.get("port_location", "front")
    pr = {**DEFAULT_PRIORITIES, **(req.get("priorities") or {})}
    min_tier = int(req.get("min_tier", 1))
    allow_dual = bool(req.get("allow_dual_woofers", True))
    top_n = int(req.get("top_n", 8))
    sim_cfg = req.get("sim") or {}
    stock_only = bool(req.get("in_stock_only", False))

    db = [d for d in drivers_db.all_drivers().values() if d.price_eur > 0 and d.tier >= min_tier and (d.in_stock or not stock_only)]
    woofers = [d for d in db if d.role in ("woofer", "midwoofer") and d.has_box_model]
    mids = [d for d in db if d.role in ("mid", "midwoofer")]
    tweeters = [d for d in db if d.role == "tweeter"]
    mid_opts = ([None] if ways in ("2", "any") else []) + (mids if ways in ("3", "any") else [])

    rejected = {"budget": 0, "fit": 0, "crossover": 0}
    bass_cache, cands = {}, []
    for W in woofers:
        for n in ([1, 2] if allow_dual else [1]):
            if W.depth_mm + 10 > g.int_d:
                rejected["fit"] += 1
                continue
            for M in mid_opts:
                if M is W:
                    continue
                if M is None and W.role != "midwoofer" and W.fmax < 2500:
                    continue  # pure woofers cannot reach a tweeter
                chamber = mid_chamber(M, mid_chamber_volume_target(M), g.int_d) if (M and M.has_box_model) else None
                for T in tweeters:
                    price = 2 * (W.price_eur * n + (M.price_eur if M else 0) + T.price_eur)
                    if price > budget:
                        rejected["budget"] += 1
                        continue
                    lay = auto_layout(g, W, n, M, T, "auto")
                    if lay["positions"] is None:
                        rejected["fit"] += 1
                        continue
                    net = volume_budget(g, W, n, M, T, chamber)["net_L"]
                    if net < 5:
                        rejected["fit"] += 1
                        continue
                    key = (W.id, n, round(net, 0))
                    if key not in bass_cache:
                        s = sealed_metrics(W, net, n, fill=max(g.fill, 0.6))
                        v = optimise_vented(W, net, n, fill=g.fill)
                        bass_cache[key] = (s, v)
                    s, v = bass_cache[key]
                    vented = box_pref == "vented" or (box_pref == "auto" and v["f3"] < s["f3"] - 5 and W.Qts < 0.5)
                    f3 = v["f3"] if vented else s["f3"]
                    mid_fc = sealed_metrics(M, chamber["Vb_L"], 1, fill=0.8)["fc"] if (M is not None and chamber) else None
                    xo = choose_crossovers(W, M, T, mid_fc, mode)
                    if xo["notes"]:
                        rejected["crossover"] += 1
                        continue
                    sens_w = W.sens_db + (6 * math.log2(n) if n > 1 else 0)
                    upper = min([T.sens_db] + ([M.sens_db] if M else []))
                    deficit = max(0.0, sens_w - 2.0 - upper)  # ~2 dB of baffle-step loss helps the woofer
                    sc = (pr["bass"] * _clamp((70 - f3) / 40) +
                          pr["output"] * _clamp((W.Sd_cm2 * n * W.Xmax_mm - 500) / 3500) +
                          pr["quality"] * ((W.tier + (M.tier if M else W.tier) + T.tier) / 3 - 1) / 4 +
                          pr["value"] * (1 - price / max(budget, 1)) -
                          1.5 * _clamp(deficit / 6))
                    cands.append({"score_pre": sc, "W": W, "n": n, "M": M, "T": T, "price": price,
                                  "box": "vented" if vented else "sealed", "f3_est": f3})
    cands.sort(key=lambda c: -c["score_pre"])
    # full simulation pool: best pre-scored sets, but at most 3 per woofer so every woofer gets a fair shot
    pool: list[dict] = []
    per_w: dict[tuple[str, int], int] = {}
    seen: set[tuple] = set()
    for c in cands:
        sig = (c["W"].id, c["n"], c["M"].id if c["M"] else None, c["T"].id)
        if sig in seen or per_w.get((c["W"].id, c["n"]), 0) >= 3:
            continue
        seen.add(sig)
        per_w[(c["W"].id, c["n"])] = per_w.get((c["W"].id, c["n"]), 0) + 1
        pool.append(c)
        if len(pool) >= top_n * 5:
            break
    results = []
    for c in pool:
        design = {
            "cabinet": cab,
            "drivers": {"woofer": {"id": c["W"].id, "count": c["n"]}, "mid": {"id": c["M"].id} if c["M"] else None,
                        "tweeter": {"id": c["T"].id}},
            "box": {"type": c["box"], "port": {"location": port_loc}},
            "crossover": {"mode": mode},
            "sim": {**sim_cfg, "points": 200},
        }
        try:
            r = simulate_design(design)
        except ValueError:
            continue
        m = r["metrics"]
        acc = _clamp((6 - m["deviation_db"]) / 4.5)
        out = _clamp((m["max_spl_40hz"] - 90) / 20)
        bass = _clamp((70 - (m["woofer_f3_hz"])) / 40)
        price = m["price_drivers_pair_eur"]
        sc = (pr["bass"] * bass + pr["output"] * out + pr["accuracy"] * acc +
              pr["quality"] * (((c["W"].tier + (c["M"].tier if c["M"] else c["W"].tier) + c["T"].tier) / 3) - 1) / 4 +
              pr["value"] * (1 - price / max(budget, 1)) - 0.6 * len(r["warnings"]) -
              0.4 * sum(1 for dv in (c["W"], c["M"], c["T"]) if dv is not None and not dv.in_stock) -
              0.25 * max(0.0, 86.0 - m["sensitivity_db_2v83_1m"]))
        rd = r["design"]
        rd["sim"]["points"] = 360
        f = r["curves"]["f"]
        idx = list(range(0, len(f), 3))
        results.append({"score": round(sc, 3), "design": rd, "metrics": m, "warnings": r["warnings"],
                        "curve": {"f": [f[i] for i in idx], "sum": [round(r["curves"]["sum"][i], 2) for i in idx]},
                        "drivers": {k: (None if v is None else {"id": v["id"], "brand": v["brand"], "model": v["model"],
                                                                 "price_eur": v["price_eur"], "in_stock": v["in_stock"],
                                                                 "shop": v.get("shop"), "outer_d_mm": v["outer_d_mm"],
                                                                 "Sd_cm2": v["Sd_cm2"], "nominal_mm": v["nominal_mm"]})
                                    for k, v in r["drivers"].items()},
                        "positions": rd["layout"]["positions"], "port": r["port"],
                        "soldering": r["soldering"]["required"],
                        "summary": {"woofer": f"{c['n']}x {c['W'].brand} {c['W'].model}",
                                    "mid": f"{c['M'].brand} {c['M'].model}" if c["M"] else None,
                                    "tweeter": f"{c['T'].brand} {c['T'].model}"},
                        "score_parts": {"bass": round(bass, 2), "output": round(out, 2), "accuracy": round(acc, 2)}})
    results.sort(key=lambda x: -x["score"])
    diverse, per_w = [], {}
    for x in results:  # show variety: at most 2 sets per woofer
        k = x["design"]["drivers"]["woofer"]["id"]
        if per_w.get(k, 0) < 2:
            diverse.append(x)
            per_w[k] = per_w.get(k, 0) + 1
    results = (diverse + [x for x in results if x not in diverse])[:top_n]
    _explain(results, budget)
    return {"results": results, "evaluated": len(cands), "rejected": rejected,
            "geometry": g.to_dict()}


def _explain(results: list, budget: float) -> None:
    """Human-readable pros / cons for each ranked candidate (relative to the others)."""
    if not results:
        return
    ms = [r["metrics"] for r in results]
    best = {"f3": min(m["woofer_f3_hz"] for m in ms), "dev": min(m["deviation_db"] for m in ms),
            "spl": max(m["max_spl_40hz"] for m in ms), "price": min(m["price_drivers_pair_eur"] for m in ms),
            "sens": max(m["sensitivity_db_2v83_1m"] for m in ms)}
    for r in results:
        m, pros, cons = r["metrics"], [], []
        if m["woofer_f3_hz"] <= best["f3"] + 0.5:
            pros.append(f"Deepest bass of the list (-3 dB at {m['woofer_f3_hz']:.0f} Hz)")
        elif m["woofer_f3_hz"] < 35:
            pros.append(f"Deep bass: -3 dB at {m['woofer_f3_hz']:.0f} Hz")
        elif m["woofer_f3_hz"] > 45:
            cons.append(f"Less deep bass (-3 dB at {m['woofer_f3_hz']:.0f} Hz) - room gain will help a little")
        if m["deviation_db"] <= best["dev"] + 0.05:
            pros.append(f"Smoothest simulated response (±{m['deviation_db']:.1f} dB)")
        elif m["deviation_db"] > 3.5:
            cons.append(f"Less even response (±{m['deviation_db']:.1f} dB) - needs more EQ")
        if m["max_spl_40hz"] >= best["spl"] - 0.3:
            pros.append(f"Most bass output ({m['max_spl_40hz']:.0f} dB at 40 Hz)")
        if m["price_drivers_pair_eur"] <= best["price"] + 0.5:
            pros.append(f"Cheapest set (€{m['price_drivers_pair_eur']:.0f} per pair)")
        elif m["price_drivers_pair_eur"] > 0.9 * budget:
            cons.append("Uses almost all of the budget")
        if m["sensitivity_db_2v83_1m"] >= best["sens"] - 0.2:
            pros.append(f"Most efficient ({m['sensitivity_db_2v83_1m']:.1f} dB/2.83 V/1 m)")
        if m["box_type"] == "sealed":
            pros.append("Sealed box: no port noise, tight bass, easy build")
        elif m["fb_hz"]:
            cons.append(f"Needs a port (tuned {m['fb_hz']:.0f} Hz) and a subsonic filter below ~{0.8 * m['fb_hz']:.0f} Hz")
        oos = [d["model"] for d in r["drivers"].values() if d and not d["in_stock"]]
        if oos:
            cons.append("Currently out of stock: " + ", ".join(oos))
        cons += r["warnings"]
        r["pros"], r["cons"] = pros, cons


GOLDEN = (1.0, 1.272, 1.618)  # W : D : H  (internal)


def reverse(req: dict) -> dict:
    """Box from drivers: alignment -> net volume -> gross volume -> outer dimensions -> full design."""
    W = drivers_db.require(req["woofer"])
    n = int(req.get("woofer_count", 1))
    M = drivers_db.get(req.get("mid"))
    T = drivers_db.require(req["tweeter"])
    t = float(req.get("wall_t", 18))
    align = req.get("alignment", "auto")
    qtc = float(req.get("qtc", 0.707))
    qtc = max(qtc, round(W.Qts * math.sqrt(2), 3))  # keep a sealed box <= Vas (high-Qts drivers otherwise need huge boxes)
    auto = align == "auto"
    if align == "auto":  # vented when it buys real bass extension (low/moderate Qts), else sealed
        sv, vv = sealed_for_qtc(W, qtc, n), qb3(W, n)
        f3s = sealed_metrics(W, sv["Vb_L"], n)["f3"] if sv["Vb_L"] else 1e9
        f3v = optimise_vented(W, vv["Vb_L"], n)["f3"]
        align = "vented" if W.Qts <= 0.5 and f3v < f3s - 5 else "sealed"
    if align == "sealed":
        a = sealed_for_qtc(W, qtc, n)
        if a["Vb_L"] is None:
            a = {"Vb_L": (W.Vas_L or 20.0) * n * 0.5, "note": a["note"]}
        net, fb = a["Vb_L"], None
    else:
        a = qb3(W, n)
        net, fb = a["Vb_L"], a["fb"]
    fill = float(req.get("fill", 0.5 if align == "vented" else 0.8))
    net_target = net / (1 + 0.2 * fill)
    chamber_v = mid_chamber_volume_target(M) if (M and M.has_box_model) else 0
    # width from the widest driver (+ margins); vertical layout
    from .layout import GAP, MARGIN
    min_w_in = max(W.outer_d_mm, (M.outer_d_mm if M else 0), T.outer_d_mm) + 2 * MARGIN + 6
    mid_d = max(M.outer_d_mm, M.cutout_d_mm + 2 * 20) if (M and M.has_box_model) else (M.outer_d_mm if M else 0)
    min_w_in = max(min_w_in, mid_d + 2 * MARGIN + 6)
    min_h_ext = 2 * MARGIN + T.outer_d_mm + (mid_d + GAP if M else 0) + n * (W.outer_d_mm + GAP) + 6 + 2 * t
    fixed = dict(req.get("fixed") or {})
    extra_h = 0.0
    port_loc = req.get("port_location", "front")
    for _attempt in range(12):  # grow the height until the auto-layout fits inside the cavity
        gross = net_target * 1.0
        for _ in range(4):
            dims = _solve_dims(gross, min_w_in, min_h_ext - 2 * t + extra_h, fixed, t)
            cab = {"mode": "free", "outer_w": dims[0] + 2 * t, "outer_h": dims[2] + 2 * t,
                   "outer_d": dims[1] + 2 * t, "wall_t": t, "baffle_t": t, "fill": fill, "bracing_pct": 2.0}
            g = geometry(cab)
            chamber = mid_chamber(M, chamber_v, g.int_d) if chamber_v else None
            vb = volume_budget(g, W, n, M, T, chamber, port_ext_L=0.012 * net if fb else 0)
            gross += net_target - vb["net_L"]
        design = {"cabinet": cab,
                  "drivers": {"woofer": {"id": W.id, "count": n}, "mid": {"id": M.id} if M else None, "tweeter": {"id": T.id}},
                  "box": {"type": align, "fb": round(fb, 1) if fb else None,
                          "port": {"location": port_loc}},
                  "layout": {"style": req.get("layout_style", "vertical")},
                  "crossover": {"mode": req.get("crossover_mode", "active")}}
        probe = simulate_design(deep_merge(DEFAULT_DESIGN, {**design, "sim": {"points": 60}}))
        if not fixed.get("outer_h") and any("dashed cavity line" in w or "chamber" in w for w in probe["warnings"]):
            extra_h += 20.0  # layout does not fit yet: grow the height first
            continue
        pp = probe.get("port")
        if align == "vented" and port_loc == "front" and any("No free space for the" in w for w in probe["warnings"]):
            port_loc = "rear"  # crowded baffle: put the port on the back panel instead
            continue
        if auto and align == "vented" and (not pp or not pp["fits"] or pp["vel_peak_ms"] > 1.4 * pp["vel_limit_ms"]
                                           or any("No free space for the" in w for w in probe["warnings"])):
            align, fb = "sealed", None  # no workable port in this size: sealed instead
            a = sealed_for_qtc(W, qtc, n)
            net = a["Vb_L"] or (W.Vas_L or 20.0) * n * 0.5
            net_target = net / (1 + 0.2 * 0.8)
            fill = 0.8
            continue
        break
    design = deep_merge(DEFAULT_DESIGN, design)
    r = simulate_design(design)
    return {"alignment": {"type": align, **{k: (round(v, 3) if isinstance(v, float) else v) for k, v in a.items()}},
            "net_target_L": round(net_target, 2), "result": r}


def _solve_dims(V_L, min_w, min_h, fixed: dict, t: float):
    V = V_L * 1e6
    fw = fixed.get("outer_w")
    fh = fixed.get("outer_h")
    fd = fixed.get("outer_d")
    w = (fw - 2 * t) if fw else None
    h = (fh - 2 * t) if fh else None
    dp = (fd - 2 * t) if fd else None
    if w and h and not dp:
        dp = V / (w * h)
    elif w and dp and not h:
        h = V / (w * dp)
    elif h and dp and not w:
        w = V / (h * dp)
    elif not (w and h and dp):
        if w is None:
            base = (V / (GOLDEN[1] * GOLDEN[2])) ** (1 / 3)
            w = max(min_w, base if h is None and dp is None else 0)
        if h is None and dp is None:
            dp = max(math.sqrt(V / w / GOLDEN[2] * GOLDEN[1]), 150)
            h = V / (w * dp)
            if h < min_h:
                h = min_h
                dp = V / (w * h)
        elif h is None:
            h = V / (w * dp)
        else:
            dp = V / (w * h)
    assert w is not None and dp is not None and h is not None
    return round(w, 0), round(dp, 0), round(h, 0)
