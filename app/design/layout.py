"""Automatic front-baffle layout and geometric validation."""
from __future__ import annotations

from typing import Any

import math

MARGIN = 3.0  # flange to the cavity opening (dashed line): drivers stay fully inside it
MIN_WEB = 10.0  # default MDF left between two flush-mount rebates (thinner webs chip/crack)
REBATE_CLEAR = 0.5  # rebate radius = flange radius + this
GAP = MIN_WEB + 2 * REBATE_CLEAR  # flange to flange


def _fits_circle(x, y, r, w, h, m=MARGIN):
    return m + r <= x <= w - m - r and m + r <= y <= h - m - r


def _in_open(x, y, r, g, m=MARGIN):
    """Flange (radius r) completely inside the cavity opening (the dashed line on the baffle)."""
    return (g.open_x + r + m - 0.01 <= x <= g.open_x + g.open_w - r - m + 0.01 and
            g.open_y + r + m - 0.01 <= y <= g.open_y + g.open_h - r - m + 0.01)


def _in_opening(x, y, r, g):
    return (g.open_x + r + 3 <= x <= g.open_x + g.open_w - r - 3 and
            g.open_y + r + 3 <= y <= g.open_y + g.open_h - r - 3)


def _min_x_clear(x_ref, y_ref, r_ref, y, r, gap=GAP):
    need = r_ref + r + gap
    dy = abs(y - y_ref)
    return x_ref - math.sqrt(need ** 2 - dy ** 2) if dy < need else x_ref + 1e9


def auto_layout(g, woofer, n_woofer, mid, tweeter, style: str = "auto", side: str = "left",
                min_web: float = MIN_WEB) -> dict:
    """Positions for the LEFT speaker (tweeter towards the right/inner edge). Right is mirrored."""
    GAP = min_web + 2 * REBATE_CLEAR
    W, H = g.open_w, g.open_h  # positions are computed inside the cavity opening, then shifted to baffle coords
    rw = woofer.outer_d_mm / 2
    rt = tweeter.outer_d_mm / 2 if tweeter else 0
    rm = mid.outer_d_mm / 2 if mid else 0
    if mid and mid.has_box_model:  # its sealed chamber (6 mm air + 12 mm wall around the cut-out) needs room too
        rm = max(rm, mid.cutout_d_mm / 2 + 6 + 12 + 2)
    tries = [style] if style != "auto" else (["column", "row", "vertical"] if W >= H else ["vertical", "column", "row"])
    errors = []
    for st in tries:
        pos: dict[str, Any] = {}
        if st == "column":
            col_r = max(rm, rt)
            total = 2 * rt + (GAP + 2 * rm if mid else 0)
            if total > H - 2 * MARGIN:
                errors.append("column: mid+tweeter taller than baffle"); continue
            xc = W - MARGIN - col_r
            y0 = (H - total) / 2
            if mid:
                pos["mid"] = {"x": xc, "y": y0 + rm}
                pos["tweeter"] = {"x": xc, "y": y0 + 2 * rm + GAP + rt}
            else:
                pos["tweeter"] = {"x": xc, "y": H / 2}
            ws = []
            ref = [(p["x"], p["y"], rm if k == "mid" else rt) for k, p in pos.items()]
            for _ in range(n_woofer):
                y = H / 2
                x = min(_min_x_clear(rx, ry, rr, y, rw, GAP) for rx, ry, rr in ref)
                ws.append({"x": x, "y": y})
                ref.append((x, y, rw))
            pos["woofer"] = ws
        elif st == "row":
            y = H / 2
            x = W - MARGIN - rt
            pos["tweeter"] = {"x": x, "y": y}
            x -= rt + GAP + (rm if mid else rw)
            if mid:
                pos["mid"] = {"x": x, "y": y}
                x -= rm + GAP + rw
            ws = []
            for _ in range(n_woofer):
                ws.append({"x": x, "y": y})
                x -= 2 * rw + GAP
            pos["woofer"] = ws
        elif st == "vertical":
            x = W / 2
            y = H - MARGIN - rt
            pos["tweeter"] = {"x": x, "y": y}
            y -= rt + GAP + (rm if mid else rw)
            if mid:
                pos["mid"] = {"x": x, "y": y}
                y -= rm + GAP + rw
            ws = []
            for _ in range(n_woofer):
                ws.append({"x": x, "y": y})
                y -= 2 * rw + GAP
            pos["woofer"] = ws
        for v in pos.values():
            for p in (v if isinstance(v, list) else [v]):
                p["x"] += g.open_x
                p["y"] += g.open_y
        issues = validate_layout(g, pos, woofer, mid, tweeter, None, min_web)
        hard = [i for i in issues if i["level"] == "error"]
        if not hard:
            out = {"style": st, "positions": pos, "issues": issues}
            return mirror(out, g.baffle_w) if side == "right" else out
        errors += [f"{st}: {i['msg']}" for i in hard]
    return {"style": None, "positions": None, "issues": [{"level": "error", "msg": e} for e in errors]}


def mirror(layout: dict, W: float) -> dict:
    def m(p):
        return {**p, "x": W - p["x"]}
    pos = layout["positions"]
    new = {k: ([m(p) for p in v] if isinstance(v, list) else m(v)) for k, v in pos.items()}
    return {**layout, "positions": new}


def circles(pos, woofer, mid, tweeter, port=None):
    out = []
    for i, p in enumerate(pos.get("woofer", [])):
        out.append(("woofer%d" % (i + 1), p["x"], p["y"], woofer.outer_d_mm / 2, woofer.cutout_d_mm / 2))
    if mid and pos.get("mid"):
        out.append(("mid", pos["mid"]["x"], pos["mid"]["y"], mid.outer_d_mm / 2, mid.cutout_d_mm / 2))
    if tweeter and pos.get("tweeter"):
        out.append(("tweeter", pos["tweeter"]["x"], pos["tweeter"]["y"], tweeter.outer_d_mm / 2, tweeter.cutout_d_mm / 2))
    if port and port.get("location") == "front":
        for i, p in enumerate(pos.get("port", [])):
            r = port["outer_d_mm"] / 2 + port.get("flange_mm", 0)
            out.append(("port%d" % (i + 1), p["x"], p["y"], r, port["outer_d_mm"] / 2))
    return out


def clearances(g, pos, woofer, mid, tweeter, port=None) -> list:
    """MDF web left between every pair of flush-mount rebates (negative = overlap)."""
    cs = circles(pos, woofer, mid, tweeter, port)
    out = []
    for i in range(len(cs)):
        for j in range(i + 1, len(cs)):
            a, b = cs[i], cs[j]
            dist = math.hypot(a[1] - b[1], a[2] - b[2])
            web = dist - a[3] - b[3] - 2 * REBATE_CLEAR
            out.append({"a": a[0], "b": b[0], "cc_mm": round(dist, 1), "web_mm": round(web, 1),
                        "ax": a[1], "ay": a[2], "ar": a[3], "bx": b[1], "by": b[2], "br": b[3]})
    return out


def validate_layout(g, pos, woofer, mid, tweeter, port, min_web: float = MIN_WEB) -> list:
    issues = []
    for name, x, y, r, rc in circles(pos, woofer, mid, tweeter, port):
        if not _in_open(x, y, r, g, MARGIN - 0.05):
            issues.append({"level": "error", "msg": f"{name}: flange crosses the dashed cavity line (cabinet wall behind the baffle)"})
    for c in clearances(g, pos, woofer, mid, tweeter, port):
        if c["web_mm"] < 0:
            issues.append({"level": "error", "msg": f"{c['a']} overlaps {c['b']} by {-c['web_mm']:.0f} mm"})
        elif c["web_mm"] < min_web - 0.05:
            issues.append({"level": "error", "msg": f"{c['a']} and {c['b']} leave only {c['web_mm']:.0f} mm of MDF between "
                                                   f"their rebates (min {min_web:.0f} mm) - it may chip when routing"})
    if mid and tweeter and pos.get("mid") and pos.get("tweeter"):
        cc = math.hypot(pos["mid"]["x"] - pos["tweeter"]["x"], pos["mid"]["y"] - pos["tweeter"]["y"])
        issues.append({"level": "info", "msg": f"mid-tweeter centre distance {cc:.0f} mm"})
    return issues


def place_front_ports(g, pos, woofer, mid, tweeter, port: dict, n: int, side: str = "left", min_web: float = MIN_WEB) -> list:
    """Find free spots on the baffle for n front ports, preferring the outer-bottom region."""
    r = port["outer_d_mm"] / 2 + port.get("flange_mm", 0)
    rc = port["outer_d_mm"] / 2
    GAP = min_web + 2 * REBATE_CLEAR
    found: list[dict[str, float]] = []
    occupied = [(c[1], c[2], c[3]) for c in circles(pos, woofer, mid, tweeter)]
    step = 4.0
    best = []
    y = g.open_y + MARGIN + r
    while y <= g.open_y + g.open_h - MARGIN - r:
        x = g.open_x + MARGIN + r
        while x <= g.open_x + g.open_w - MARGIN - r:
            if all(math.hypot(x - ox, y - oy) >= r + orr + GAP for ox, oy, orr in occupied):
                outer = x if side == "left" else g.baffle_w - x
                best.append((outer + 0.6 * y, x, y))
            x += step
        y += step
    best.sort()
    for _, x, y in best:
        if len(found) >= n:
            break
        if all(math.hypot(x - fx["x"], y - fx["y"]) >= 2 * r + GAP for fx in found):
            found.append({"x": x, "y": y})
    return found


def _rect_circle(rx0, ry0, rx1, ry1, cx, cy, r) -> bool:
    nx, ny = min(max(cx, rx0), rx1), min(max(cy, ry0), ry1)
    return (nx - cx) ** 2 + (ny - cy) ** 2 < r * r


def chamber_rect(pos, chamber):
    """Outer footprint of the mid chamber behind the baffle, in baffle (front-view) coordinates."""
    cx = pos["mid"]["x"] + chamber["offset_x"]
    cy = pos["mid"]["y"] + chamber["offset_y"]
    return (cx - chamber["ext_w"] / 2, cy - chamber["ext_h"] / 2, cx + chamber["ext_w"] / 2, cy + chamber["ext_h"] / 2)


def chamber_collisions(g, pos, woofer, tweeter, chamber, port=None, clearance: float = 2.0) -> list:
    """The mid's sealed chamber must not hit woofer baskets, the tweeter body, port tubes or cabinet walls."""
    if not chamber or not pos.get("mid"):
        return []
    x0, y0, x1, y1 = chamber_rect(pos, chamber)
    out = []
    m, w = pos["mid"], chamber["wall"]
    need = chamber["inner_a"] and (chamber.get("mid_cutout_mm", 0) / 2 + 6)
    if need and not (x0 + w + need - 0.5 <= m["x"] <= x1 - w - need + 0.5 and y0 + w + need - 0.5 <= m["y"] <= y1 - w - need + 0.5):
        out.append({"level": "error", "msg": "the mid chamber cannot be built around the mid here (a neighbour leaves no room for its walls)"})
    if x0 < g.open_x - 0.5 or y0 < g.open_y - 0.5 or x1 > g.open_x + g.open_w + 0.5 or y1 > g.open_y + g.open_h + 0.5:
        out.append({"level": "error", "msg": f"mid chamber ({chamber['ext_w']:.0f} x {chamber['ext_h']:.0f} mm) does not fit inside the cabinet walls"})
    for i, p in enumerate(pos.get("woofer", [])):
        if _rect_circle(x0, y0, x1, y1, p["x"], p["y"], woofer.outer_d_mm / 2 + clearance):
            out.append({"level": "error", "msg": f"woofer{i + 1} overlaps the mid chamber outline (its frame and screws must stay clear of the chamber walls)"})
    if tweeter and pos.get("tweeter"):
        p = pos["tweeter"]
        if _rect_circle(x0, y0, x1, y1, p["x"], p["y"], tweeter.outer_d_mm / 2 + clearance):
            out.append({"level": "error", "msg": "tweeter overlaps the mid chamber outline"})
    if port and port.get("location") in ("front", "rear") and port.get("shape") == "round":
        for i, p in enumerate(pos.get("port", [])):
            if _rect_circle(x0, y0, x1, y1, p["x"], p["y"], port["outer_d_mm"] / 2 + port.get("flange_mm", 0) + clearance):
                out.append({"level": "error", "msg": f"mid chamber collides with port tube {i + 1}"})
    return out


def repair_chamber(g, pos: dict, W, M, T, chamber: dict, style: str) -> tuple[dict, dict | None]:
    """Auto-layout only: push the woofer(s) away from the mid until the mid chamber fits."""
    import copy
    from .cabinet import chamber_for
    pos = copy.deepcopy(pos)
    cur_ch: dict | None = chamber
    for _ in range(80):
        if not cur_ch or not any("woofer" in c["msg"] for c in chamber_collisions(g, pos, W, T, cur_ch)):
            break
        for p in pos["woofer"]:
            if style == "vertical":
                p["y"] += -2.0 if p["y"] < pos["mid"]["y"] else 2.0
            else:
                p["x"] += -2.0 if p["x"] < pos["mid"]["x"] else 2.0
        cur_ch = chamber_for(g, pos, W, M, T)
    return pos, cur_ch


def check_layout(design: dict, port: dict | None = None) -> dict:
    """Fast geometric check (no acoustics) used while dragging."""
    from . import drivers_db
    from .cabinet import chamber_for, geometry
    from .system import DEFAULT_DESIGN
    from .utils import deep_merge
    d = deep_merge(DEFAULT_DESIGN, design)
    W = drivers_db.get(d["drivers"]["woofer"]["id"])
    M = drivers_db.get((d["drivers"].get("mid") or {}).get("id"))
    T = drivers_db.get(d["drivers"]["tweeter"]["id"])
    g = geometry(d["cabinet"])
    pos = d["layout"]["positions"]
    chamber = chamber_for(g, pos, W, M, T)
    fp = port if port and port.get("location") == "front" and port.get("shape") == "round" else None
    issues = validate_layout(g, pos, W, M, T, fp, float(d["layout"].get("min_web_mm") or 10))
    issues += chamber_collisions(g, pos, W, T, chamber, port)
    errors = [i["msg"] for i in issues if i["level"] == "error"]
    return {"ok": not errors, "errors": errors, "chamber": chamber}
