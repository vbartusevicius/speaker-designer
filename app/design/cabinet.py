"""Cabinet geometry: from either an existing furniture compartment ("fit") or a new box ("free").

Coordinates: baffle seen from the front, origin bottom-left, mm.  z = depth from the
inner face of the baffle towards the back.
"""
from __future__ import annotations

import math
from dataclasses import dataclass, asdict

DEFAULT_FIT = {
    "mode": "fit",
    "inner_w": 500.0, "inner_h": 400.0, "inner_d": 350.0,
    "wall_t": 18.0, "door_recess": 20.0,
    "baffle_t": 18.0, "baffle_overlay": 9.0,
    "back": "solid",  # solid | replace_inside | replace_outside | keep
    "back_new_t": 18.0,
    "bracing_pct": 2.0, "fill": 0.5,
    "material": "MDF 18 mm",
    "bottom_drillable": True,
}


@dataclass
class Geometry:
    mode: str
    baffle_w: float
    baffle_h: float
    baffle_t: float
    open_x: float  # cavity opening rectangle in baffle coordinates
    open_y: float
    open_w: float
    open_h: float
    int_w: float
    int_h: float
    int_d: float
    wall_t: float
    back_t: float
    gross_L: float
    outer_w: float
    outer_h: float
    outer_d: float
    bracing_pct: float
    fill: float
    back_mode: str

    def to_dict(self):
        return asdict(self)


def geometry(cab: dict) -> Geometry:
    c = {**DEFAULT_FIT, **(cab or {})}
    t = float(c["wall_t"])
    bt = float(c["baffle_t"])
    if c["mode"] == "free":
        ow, oh, od = float(c["outer_w"]), float(c["outer_h"]), float(c["outer_d"])
        iw, ih = ow - 2 * t, oh - 2 * t
        idp = od - bt - t
        return Geometry("free", ow, oh, bt, t, t, iw, ih, iw, ih, idp, t, t,
                        iw * ih * idp * 1e-6, ow, oh, od, float(c["bracing_pct"]), float(c["fill"]), "new")
    iw, ih, idp = float(c["inner_w"]), float(c["inner_h"]), float(c["inner_d"])
    ov = float(c["baffle_overlay"])
    back_loss = float(c["back_new_t"]) if c["back"] == "replace_inside" else 0.0
    gain = max(0.0, float(c["door_recess"]) - bt)
    d_int = idp - back_loss + gain
    return Geometry("fit", iw + 2 * ov, ih + 2 * ov, bt, ov, ov, iw, ih, iw, ih, d_int, t,
                    (float(c["wall_t"]) if c["back"] == "solid" else float(c["back_new_t"]) if c["back"] != "keep" else 5.0),
                    iw * ih * d_int * 1e-6, iw + 2 * t, ih + 2 * t, idp + float(c["door_recess"]) + 5,
                    float(c["bracing_pct"]), float(c["fill"]), c["back"])


def mid_chamber(mid, vb_L: float, max_depth: float, span_x=None, span_y=None, cx=None, cy=None,
                wall: float = 12.0) -> dict:
    """Sealed MDF sub-enclosure behind the midrange (inner w x h x depth), as close to a cube as the
    free space allows so its depth standing wave stays above the mid band.
    span_x/span_y: (min, max) interior coordinates available for the outer walls."""
    need = vb_L * 1e6 + mid.displacement_L * 1e6
    a_min = mid.cutout_d_mm + 12.0
    cap_w = max(a_min, (span_x[1] - span_x[0] - 2 * wall) if span_x else 400.0)
    cap_h = max(a_min, (span_y[1] - span_y[0] - 2 * wall) if span_y else 400.0)
    side = max(a_min, (need / 1.3) ** (1 / 3))
    w, h = min(side, cap_w), min(side, cap_h)
    if w < side:
        h = min(max(h, math.sqrt(need / 1.3 / w * w)), cap_h)
    if h < side:
        w = min(max(w, need / 1.3 / h / h * h), cap_w)
    depth = max(need / (w * h), mid.depth_mm + 15.0)
    while depth > max_depth - wall - 10 and (w < cap_w or h < cap_h):
        w, h = min(w + 10, cap_w), min(h + 10, cap_h)
        depth = max(need / (w * h), mid.depth_mm + 15.0)
    keep = mid.cutout_d_mm / 2 + 6.0  # inner walls must stay >= 6 mm outside the mid's cut-out

    def place(c, span, size):
        """Offset of the chamber centre from the mid: inside the span, and still enclosing the mid."""
        if c is None or not span:
            return 0.0
        lo = max(span[0] - c + size / 2 + wall, -(size / 2 - keep))
        hi = min(span[1] - c - size / 2 - wall, size / 2 - keep)
        return min(max(0.0, lo), hi) if lo <= hi else lo

    ox = place(cx, span_x, w)
    oy = place(cy, span_y, h)
    ew, eh, ed = w + 2 * wall, h + 2 * wall, depth + wall
    return {"inner_w": round(w, 1), "inner_h": round(h, 1), "inner_a": round(min(w, h), 1),
            "inner_depth": round(depth, 1), "wall": wall,
            "ext_w": round(ew, 1), "ext_h": round(eh, 1), "ext_a": round(max(ew, eh), 1), "ext_depth": round(ed, 1),
            "offset_x": round(ox, 1), "offset_y": round(oy, 1), "mid_cutout_mm": mid.cutout_d_mm,
            "Vb_L": round(w * h * depth * 1e-6 - mid.displacement_L, 2),
            "ext_volume_L": round(ew * eh * ed * 1e-6, 2),
            "depth_mode_hz": round(343000.0 / (2 * depth), 0),
            "tube_alt": {"inner_d": round(math.sqrt(4 * need / (math.pi * depth)), 0), "length": round(depth, 0)}}


def mid_chamber_volume_target(mid) -> float:
    from ..physics.alignments import sealed_for_qtc
    if not mid.has_box_model:
        return 0.0
    r = sealed_for_qtc(mid, 0.75)
    vb = r["Vb_L"] if r["Vb_L"] else 1.5 * mid.Vas_L
    return float(min(max(vb, 0.8), 8.0))


def volume_budget(g: Geometry, woofer, n_woofer: int, mid, tweeter, chamber: dict | None,
                  port_ext_L: float = 0.0, braces_L: float | None = None) -> dict:
    items = [("Gross internal", g.gross_L)]
    items.append((f"Woofer body x{n_woofer}", -woofer.displacement_L * n_woofer))
    if mid is not None:
        items.append(("Mid chamber (external)" if chamber else "Midrange body",
                      -(chamber["ext_volume_L"] if chamber else mid.displacement_L)))
    if tweeter is not None:
        items.append(("Tweeter body", -max(0.0, tweeter.displacement_L * 0.3)))
    if port_ext_L:
        items.append(("Port tube", -port_ext_L))
    br = g.gross_L * g.bracing_pct / 100.0 if braces_L is None else braces_L
    items.append(("Bracing", -br))
    net = sum(v for _, v in items)
    return {"items": [{"label": k, "L": round(v, 2)} for k, v in items], "net_L": round(net, 2),
            "effective_L": round(net * (1 + 0.2 * g.fill), 2)}


def chamber_for(g: Geometry, pos: dict, W, M, T) -> dict | None:
    """Size the midrange's sealed chamber, preferring the side away from the woofer(s) and tweeter."""
    if not (M and M.has_box_model and pos.get("mid")):
        return None
    mx_, my_ = pos["mid"]["x"] - g.open_x, pos["mid"]["y"] - g.open_y
    x_lo, x_hi = 0.0, g.int_w
    for p in pos.get("woofer", []):
        wx, wy, wr = p["x"] - g.open_x, p["y"] - g.open_y, W.outer_d_mm / 2 + 3
        if abs(wy - my_) < wr + M.cutout_d_mm / 2 + 40:
            if wx < mx_:
                x_lo = max(x_lo, wx + wr)
            else:
                x_hi = min(x_hi, wx - wr)
    y_lo, y_hi = 0.0, g.int_h
    if T and pos.get("tweeter"):
        tw_x, tw_y, tw_r = pos["tweeter"]["x"] - g.open_x, pos["tweeter"]["y"] - g.open_y, T.outer_d_mm / 2 + 3
        if abs(tw_x - mx_) < tw_r + M.cutout_d_mm / 2 + 30:
            if tw_y > my_:
                y_hi = min(y_hi, tw_y - tw_r)
            else:
                y_lo = max(y_lo, tw_y + tw_r)
    return mid_chamber(M, mid_chamber_volume_target(M), g.int_d, (x_lo, x_hi), (y_lo, y_hi), mx_, my_)


def damping_plan(vented: bool, port: dict | None, has_chamber: bool) -> dict:
    """Where the damping goes. Lining kills standing waves between parallel walls; stuffing a sealed box
    makes it act ~15-20 % larger. Ports must stay unobstructed."""
    plan = {"material": "polyester wadding / acoustic felt, 20-25 mm (or 25-30 kg/m³ mineral-wool batts in a fabric sleeve)",
            "lining_mm": 25, "walls": ["back", "top", "bottom", "left", "right"],
            "fill_pct": 0 if vented else 50,
            "fill_note": "" if vented else "loosely fill about half the volume with polyester fibre (~10 g per litre); do not compress",
            "keep_clear_mm": round(port["d_mm"] if port and port.get("d_mm") else (port["slot_h_mm"] * 2 if port else 0)),
            "mid_chamber": "fill loosely with polyester fibre or wool" if has_chamber else None}
    if vented:
        plan["note"] = f"line the walls only; keep {plan['keep_clear_mm']} mm clear in front of the inner port opening"
        if port and port["location"] == "bottom":
            plan["walls"] = ["back", "top", "left", "right"]
    else:
        plan["note"] = "line all walls, then loose fill"
    return plan
