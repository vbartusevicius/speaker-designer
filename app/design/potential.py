"""What a cabinet can achieve: best bass extension / output over every woofer in the database that fits."""
from __future__ import annotations

import math

import numpy as np

from ..physics.alignments import optimise_vented, sealed_metrics
from ..physics.enclosure import Box, simulate
from ..physics.port import port_length_mm
from . import drivers_db
from .cabinet import geometry

TYPICAL_MID_CHAMBER_L = 8.0  # external volume of a typical 3-way mid chamber
PORT_ALLOWANCE_L = 1.0
REFERENCES = [  # (Hz, label) for the "what does it mean" scale
    (55, "typical bookshelf speaker"), (40, "typical floor-standing speaker"), (25, "home-cinema subwoofer"),
]
NOTES = [(41.2, "lowest note of a 4-string bass guitar (E1)"), (27.5, "lowest piano key (A0)"),
         (32.7, "lowest note of a 5-string bass (B0) / pipe-organ C1"), (55.0, "kick drum body (~50-60 Hz)")]


def _max_spl_40(drv, box) -> float:
    f = np.array([40.0])
    v = math.sqrt(drv.Pe_W * drv.Re)
    sim = simulate(drv, box, f, vin=v, use_le=False, breakup=False)
    return float(sim.max_spl(None)["spl"][0])


def potential(cab: dict, three_way: bool = True) -> dict:
    g = geometry(cab)
    rows = []
    for d in drivers_db.all_drivers().values():
        if d.price_eur <= 0 or d.role not in ("woofer", "midwoofer") or not d.has_box_model:
            continue
        fits = (d.outer_d_mm + 16 <= g.baffle_h and d.cutout_d_mm + 6 <= g.open_h and d.depth_mm + 10 <= g.int_d
                and d.outer_d_mm + 16 <= g.baffle_w)
        if not fits:
            continue
        net = g.gross_L * (1 - g.bracing_pct / 100) - d.displacement_L - (TYPICAL_MID_CHAMBER_L if three_way else 0)
        if net < 5:
            continue
        s = sealed_metrics(d, net, fill=max(g.fill, 0.6))
        v = optimise_vented(d, net - PORT_ALLOWANCE_L, fill=g.fill)
        leff = port_length_mm((net - PORT_ALLOWANCE_L) * (1 + 0.2 * g.fill), v["fb"], 50.0, 1, 0.0)
        rows.append({
            "id": d.id, "name": f"{d.brand} {d.model}", "nominal_mm": d.nominal_mm, "price_eur": d.price_eur,
            "in_stock": d.in_stock, "net_L": round(net, 1),
            "sealed_f3": round(s["f3"], 1), "sealed_qtc": round(s["qtc"], 2),
            "vented_f3": round(v["f3"], 1), "vented_fb": round(v["fb"], 1),
            "max_spl_40_sealed": round(_max_spl_40(d, Box("sealed", net, fill=max(g.fill, 0.6))), 1),
            "max_spl_40_vented": round(_max_spl_40(d, Box("vented", net - PORT_ALLOWANCE_L, v["fb"], 50.0, leff, fill=g.fill)), 1),
        })
    rows.sort(key=lambda r: r["vented_f3"])
    max_frame = min(g.baffle_h, g.baffle_w) - 16
    return {
        "gross_L": round(g.gross_L, 1), "geometry": g.to_dict(), "woofers": rows,
        "best": {"vented_f3": min((r["vented_f3"] for r in rows), default=None),
                 "sealed_f3": min((r["sealed_f3"] for r in rows), default=None),
                 "max_spl_40": max((max(r["max_spl_40_sealed"], r["max_spl_40_vented"]) for r in rows), default=None)},
        "fit": {"max_frame_mm": round(max_frame, 0), "max_cutout_mm": round(g.open_h - 6, 0),
                "max_driver_depth_mm": round(g.int_d - 10, 0),
                "max_port_front_mm": round(g.int_d - 60, 0), "max_port_bottom_mm": round(g.int_h - 60, 0),
                "sizes_mm": sorted({int(r["nominal_mm"]) for r in rows})},
        "references": [{"hz": h, "label": l} for h, l in REFERENCES],
        "notes": [{"hz": h, "label": l} for h, l in NOTES],
    }
