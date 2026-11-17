"""'Optimize' button: fine-tune crossover points, levels and filter type for the flattest response.

Objective = std-dev of the 1/6-octave smoothed on-axis sum over 150 Hz-12 kHz (+ penalties for unsafe
crossover points and mid over-excursion).  Pattern search (coordinate descent with shrinking steps)
in log-frequency / dB space; polarity is re-chosen automatically at every evaluation.
"""
from __future__ import annotations

import copy
import math
from typing import Any

import numpy as np

from . import drivers_db
from .cabinet import geometry
from .layout import auto_layout, check_layout
from .system import simulate_design
from .utils import smooth_db

BAND = (150.0, 10000.0)
BAD_WORDS = ("overlap", "MDF", "collides", "crosses", "edge", "hits", "longer than", "air speed", "Xmax", "does not fit")


def objective(r, ref) -> float:
    """What the tiles show: response deviation (150 Hz-10 kHz) + overall smoothness, reward sensitivity,
    never trade away bass extension, hard penalties for anything un-buildable or over-driven."""
    f = np.array(r["curves"]["f"])
    y = np.array(r["curves"]["sum"])
    m = (f >= BAND[0]) & (f <= BAND[1])
    std = float(np.std(smooth_db(f[m], y[m], 6)))
    mt = r["metrics"]
    j = mt["deviation_db"] + std
    j -= 0.35 * (mt["sensitivity_db_2v83_1m"] - ref["sensitivity_db_2v83_1m"])
    j += 0.1 * max(0.0, mt["woofer_f3_hz"] - ref["woofer_f3_hz"])
    if r.get("port"):  # quieter port: reward air speed below ~10 m/s
        j += 0.15 * max(0.0, r["port"]["vel_peak_ms"] - 10.0)
    j += sum(5.0 for w in r["warnings"] if any(b in w for b in BAD_WORDS))
    return j + spacing_penalty(r)


def spacing_penalty(r) -> float:
    """What the on-axis curve cannot see: drivers that cross over to each other must be within ~1 wavelength
    at their crossover (else off-axis lobing / smeared stereo image), and the tweeter on the mid's vertical axis."""
    pos, dr, xc = r["design"]["layout"]["positions"], r["drivers"], r["design"]["crossover"]
    c_mm = 343000.0
    upper = ("mid", dr["mid"]) if dr.get("mid") and pos.get("mid") else ("woofer", dr["woofer"])
    up = pos[upper[0]][0] if isinstance(pos[upper[0]], list) else pos[upper[0]]
    t = pos["tweeter"]
    cc = math.hypot(up["x"] - t["x"], up["y"] - t["y"])
    min_cc = (upper[1]["outer_d_mm"] + dr["tweeter"]["outer_d_mm"]) / 2 + 11
    pen = 5.0 if cc > max(min_cc + 30, 0.9 * c_mm / xc["f_mt"]) else 0.0
    pen += 0.004 * abs(up["x"] - t["x"]) + 0.002 * max(0.0, cc - min_cc)
    if dr.get("mid") and pos.get("mid") and xc.get("f_wm"):
        m = pos["mid"]
        for w in pos.get("woofer", []):
            ccw = math.hypot(w["x"] - m["x"], w["y"] - m["y"])
            min_w = (dr["woofer"]["outer_d_mm"] + dr["mid"]["outer_d_mm"]) / 2 + 11
            if ccw > max(min_w + 60, 0.5 * c_mm / xc["f_wm"]):
                pen += 5.0
    return pen


def _score(r, ref=None) -> float:
    return objective(r, ref or r["metrics"])


def tune(design: dict, max_evals: int = 160, ref: dict | None = None) -> dict:
    base = simulate_design(design)
    ref = ref or base["metrics"]
    d0 = copy.deepcopy(base["design"])
    d0["sim"]["points"] = 200
    has_mid = d0["drivers"].get("mid") is not None
    xc = d0["crossover"]
    W = drivers_db.require(d0["drivers"]["woofer"]["id"])
    M = drivers_db.get((d0["drivers"].get("mid") or {}).get("id"))
    T = drivers_db.require(d0["drivers"]["tweeter"]["id"])
    roles = ["woofer", "mid", "tweeter"] if has_mid else ["woofer", "tweeter"]

    # parameter vector: log f_wm, log f_mt, level offsets (dB) for every way except the lowest-level one
    x = {"f_mt": math.log(xc["f_mt"])}
    if has_mid:
        x["f_wm"] = math.log(xc["f_wm"])
    for rl in roles:
        x["lv_" + rl] = float(xc["levels"][rl])
    # hard, driver-safe limits (tweeter >= k*Fs and its rated minimum, mid/woofer below break-up)
    k_tw = 2.5 if xc["mode"] == "active" else 3.0
    upper = M if (has_mid and M is not None) else W
    fmt_lo = max(T.Fs * k_tw, T.fmin, 1200.0)
    fmt_hi = max(fmt_lo * 1.05, min(upper.fmax / 1.2, 6000.0))
    bounds = {"f_mt": (math.log(fmt_lo), math.log(fmt_hi))}
    x["f_mt"] = min(max(x["f_mt"], bounds["f_mt"][0]), bounds["f_mt"][1])
    if has_mid and M is not None:
        mid_fc = base["metrics"].get("mid_chamber_fc_hz") or 0
        fwm_lo = max(2.0 * mid_fc, M.fmin, 150.0)
        fwm_hi = max(fwm_lo * 1.05, min(W.fmax / 2.5, 1000.0))
        bounds["f_wm"] = (math.log(fwm_lo), math.log(fwm_hi))
        x["f_wm"] = min(max(x["f_wm"], bounds["f_wm"][0]), bounds["f_wm"][1])
    for rl in roles:
        bounds["lv_" + rl] = (0.0, 12.0)

    kinds = [xc["kind"]] if xc["mode"] == "active" else ["LR2", "BW2"]
    evals = 0
    cache: dict[tuple[Any, ...], tuple[float, dict]] = {}

    def run(xv, kind):
        nonlocal evals
        key = (kind,) + tuple(round(v, 4) for v in xv.values())
        if key in cache:
            return cache[key]
        dd = copy.deepcopy(d0)
        lv = {rl: xv["lv_" + rl] for rl in roles}
        mn = min(lv.values())
        dd["crossover"].update(kind=kind, f_mt=round(math.exp(xv["f_mt"]), 0), polarity=None,
                               levels={k: round(v - mn, 2) for k, v in lv.items()})
        if has_mid:
            dd["crossover"]["f_wm"] = round(math.exp(xv["f_wm"]), 0)
        r = simulate_design(dd)
        evals += 1
        sc = objective(r, ref)
        cache[key] = (sc, r)
        return cache[key]

    best_overall = None
    for kind in kinds:
        cur = dict(x)
        best, _ = run(cur, kind)
        steps = {k: (0.12 if k.startswith("f_") else 1.0) for k in cur}
        while evals < max_evals and max(steps.values()) > 0.015:
            improved = False
            for k in cur:
                for sgn in (1, -1):
                    cand = dict(cur)
                    cand[k] = min(max(cur[k] + sgn * steps[k], bounds[k][0]), bounds[k][1])
                    if cand[k] == cur[k]:
                        continue
                    sc, _ = run(cand, kind)
                    if sc < best - 1e-4:
                        best, cur, improved = sc, cand, True
                        break
            if not improved:
                steps = {k: v / 2 for k, v in steps.items()}
        if best_overall is None or best < best_overall[0]:
            best_overall = (best, cur, kind)

    assert best_overall is not None
    sc, xv, kind = best_overall
    _, r = run(xv, kind)
    tuned = copy.deepcopy(r["design"])
    tuned["sim"]["points"] = design.get("sim", {}).get("points", 360) or 360
    final = simulate_design(tuned)
    if objective(final, ref) > objective(base, ref) + 1e-6:
        final = base
    b, a = base["metrics"], final["metrics"]
    bx, ax = base["design"]["crossover"], final["design"]["crossover"]
    changes = []
    if has_mid and abs(ax["f_wm"] - bx["f_wm"]) >= 5:
        changes.append(f"woofer→mid crossover {bx['f_wm']:.0f} → {ax['f_wm']:.0f} Hz")
    if abs(ax["f_mt"] - bx["f_mt"]) >= 5:
        changes.append(f"{'mid' if has_mid else 'woofer'}→tweeter crossover {bx['f_mt']:.0f} → {ax['f_mt']:.0f} Hz")
    for rl in roles:
        if abs(ax["levels"][rl] - bx["levels"][rl]) >= 0.2:
            changes.append(f"{rl} level cut {bx['levels'][rl]:.1f} → {ax['levels'][rl]:.1f} dB")
    if ax["kind"] != bx["kind"]:
        changes.append(f"filter {bx['kind']} → {ax['kind']}")
    for rl in roles:
        if ax["polarity"].get(rl) != bx["polarity"].get(rl):
            changes.append(f"{rl} polarity → {'inverted' if ax['polarity'][rl] < 0 else 'normal'}")
    return {"design": final["design"], "result": final, "evals": evals,
            "before": {"deviation_db": b["deviation_db"], "sensitivity": b["sensitivity_db_2v83_1m"], "score": round(objective(base, ref), 3)},
            "after": {"deviation_db": a["deviation_db"], "sensitivity": a["sensitivity_db_2v83_1m"], "score": round(objective(final, ref), 3)},
            "changes": changes or ["already optimal - nothing to change"]}


# ================================================================== Maximize


def _items(d, port):
    pos = d["layout"]["positions"]
    out = [("tweeter", None)] + ([("mid", None)] if pos.get("mid") else []) + [("woofer", i) for i in range(len(pos.get("woofer", [])))]
    if port and port["location"] == "front" and port["shape"] == "round":
        out += [("port", i) for i in range(len(pos.get("port", [])))]
    return out


def _pt(d, key, idx):
    p = d["layout"]["positions"][key]
    return p if idx is None else p[idx]


class _MaximizeSession:
    """Encapsulates state & search phases for global layout + port + crossover optimisation."""

    def __init__(self, design: dict) -> None:
        self.base = simulate_design(design)
        self.ref = self.base["metrics"]
        self.j_base = objective(self.base, self.ref)
        self.design = copy.deepcopy(self.base["design"])
        self.design["sim"]["points"] = 200
        self.evals = 0
        self.log: list[str] = []
        self.best_j, self.best_r = self.run(self.design)

    def run(self, dd: dict) -> tuple[float, dict]:
        self.evals += 1
        r = simulate_design(dd)
        return objective(r, self.ref), r

    def accept(self, dd: dict) -> bool:
        j, r = self.run(dd)
        if j < self.best_j - 1e-4:
            self.best_j, self.best_r = j, r
            self.design = copy.deepcopy(r["design"])
            self.design["sim"]["points"] = 200
            return True
        return False

    def valid(self, dd: dict) -> bool:
        return check_layout(dd, self.best_r["port"])["ok"]

    def tune_port(self) -> None:
        port = self.best_r["port"]
        if self.design["box"]["type"] != "vented" or not port or port["shape"] != "round":
            return
        fb0, d0 = self.design["box"]["fb"], port["d_mm"]
        start = copy.deepcopy(self.design)
        for k in (0.88, 0.91, 0.94, 0.97, 1.0, 1.03, 1.06, 1.09, 1.12):
            for dm in (None, 71.2, 85.6, 104.6):
                dd = copy.deepcopy(start)
                dd["box"]["fb"] = round(fb0 * k, 1)
                dd["box"]["port"].update(d_mm=dm, count=None)
                dd["layout"]["positions"].pop("port", None)
                self.accept(dd)
        bp = self.best_r["port"]
        if abs(self.design["box"]["fb"] - fb0) > 0.05 or bp["d_mm"] != d0:
            self.log.append(f"port {fb0:.1f} → {self.design['box']['fb']:.1f} Hz, {bp['count']}× {bp.get('tube_name') or ''} "
                            f"Ø{bp['d_mm']:.0f} × {bp['length_mm']:.0f} mm")
        self.design["box"]["port"].update(d_mm=bp["d_mm"], count=bp["count"])

    def tune_layout_style(self) -> None:
        dv = self.design["drivers"]
        W = drivers_db.get(dv["woofer"]["id"])
        M = drivers_db.get((dv.get("mid") or {}).get("id"))
        T = drivers_db.get(dv["tweeter"]["id"])
        g = geometry(self.design["cabinet"])
        n_w = int(dv["woofer"].get("count") or 1)
        min_w = float(self.design["layout"].get("min_web_mm") or 10)
        for st in ("column", "row", "vertical"):
            if st == self.design["layout"].get("style"):
                continue
            if auto_layout(g, W, n_w, M, T, st, "left", min_w)["positions"]:
                dd = copy.deepcopy(self.design)
                dd["layout"].update(positions=None, style=st)
                if self.accept(dd):
                    self.log.append(f"layout style → {st}")

    def scan_positions(self) -> None:
        for _ in range(2):
            for key, idx in _items(self.design, self.best_r["port"]):
                for axis in ("x", "y"):
                    cands = []
                    for off in range(-150, 151, 6):
                        if off == 0:
                            continue
                        dd = copy.deepcopy(self.design)
                        _pt(dd, key, idx)[axis] += off
                        if self.valid(dd):
                            cands.append(dd)
                    for dd in cands:
                        self.accept(dd)
            t = tune(self.design, max_evals=70, ref=self.ref)
            self.evals += t["evals"]
            tj = objective(t["result"], self.ref)
            if tj < self.best_j - 1e-4:
                self.best_j, self.best_r = tj, t["result"]
                self.design = copy.deepcopy(t["design"])
                self.design["sim"]["points"] = 200

    def fine_nudge(self) -> None:
        dirs = ((1, 0), (-1, 0), (0, 1), (0, -1), (1, 1), (1, -1), (-1, 1), (-1, -1))
        for step in (4, 2, 1):
            improved = True
            while improved:
                improved = False
                for key, idx in _items(self.design, self.best_r["port"]):
                    for dx, dy in dirs:
                        dd = copy.deepcopy(self.design)
                        p = _pt(dd, key, idx)
                        p["x"] += dx * step
                        p["y"] += dy * step
                        if self.valid(dd) and self.accept(dd):
                            improved = True


def maximize(design: dict) -> dict:
    """Global search for the given driver set: port tuning/pipe, layout style, axis scans,
    crossover re-tuning, and a fine 8-direction search."""
    s = _MaximizeSession(design)
    s.tune_port()
    s.tune_layout_style()
    pos0 = copy.deepcopy(s.design["layout"]["positions"])
    s.scan_positions()
    s.fine_nudge()

    moved = []
    for key, idx in _items(s.design, s.best_r["port"]):
        try:
            a_, b_ = (pos0[key] if idx is None else pos0[key][idx]), _pt(s.design, key, idx)
        except (KeyError, IndexError, TypeError):
            continue
        dist = math.hypot(a_["x"] - b_["x"], a_["y"] - b_["y"])
        if dist >= 1:
            moved.append(f"{key}{'' if idx is None else idx + 1} {dist:.0f} mm")
    if moved:
        s.log.append("moved " + ", ".join(moved))

    s.design["sim"]["points"] = design.get("sim", {}).get("points", 360) or 360
    final = simulate_design(s.design)
    if objective(final, s.ref) > s.j_base + 1e-6:
        final, s.log = s.base, ["the current design is already the best found"]
    else:
        bx, ax = s.base["design"]["crossover"], final["design"]["crossover"]
        for k_, lbl in (("f_wm", "woofer→mid"), ("f_mt", "→tweeter")):
            if bx.get(k_) and ax.get(k_) and abs(bx[k_] - ax[k_]) >= 5:
                s.log.append(f"{lbl} crossover {bx[k_]:.0f} → {ax[k_]:.0f} Hz")
        for rl, v in (ax.get("levels") or {}).items():
            if abs(v - (bx.get("levels") or {}).get(rl, v)) >= 0.2:
                s.log.append(f"{rl} level cut {bx['levels'][rl]:.1f} → {v:.1f} dB")
    b, a = s.base["metrics"], final["metrics"]
    return {"design": final["design"], "result": final, "evals": s.evals,
            "before": {"deviation_db": b["deviation_db"], "sensitivity": b["sensitivity_db_2v83_1m"], "f3": b["woofer_f3_hz"], "score": round(s.j_base, 3)},
            "after": {"deviation_db": a["deviation_db"], "sensitivity": a["sensitivity_db_2v83_1m"], "f3": a["woofer_f3_hz"], "score": round(objective(final, s.ref), 3)},
            "changes": s.log or ["the current design is already the best found"]}
