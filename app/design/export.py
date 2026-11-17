"""Manufacturing outputs: panel geometry -> DXF (CNC layers), 1:1 SVG templates, cut list, build sheet."""
from __future__ import annotations

import csv
import io
import json
import math
import zipfile

import ezdxf

from dataclasses import dataclass
from typing import Callable

LAYERS = {"OUTLINE": 7, "CUT_THROUGH": 1, "POCKET": 5, "DRILL": 3, "CENTER": 8, "TEXT": 2, "CHAMFER_REAR": 6}


@dataclass(frozen=True)
class ExportSpec:
    media_type: str
    filename: str
    render: Callable[[dict, list[dict]], bytes | str]


def _build_exporters() -> dict[str, ExportSpec]:
    return {
        "dxf": ExportSpec("application/dxf", "panels.dxf", lambda _r, parts: dxf_bytes(parts)),
        "svg": ExportSpec("image/svg+xml", "template.svg", lambda _r, parts: svg_part(parts[0])),
        "cutlist": ExportSpec("text/csv", "cutlist.csv", lambda _r, parts: cutlist_csv(parts)),
        "build": ExportSpec("text/markdown", "BUILD.md", lambda r, parts: build_notes(r, parts)),
        "zip": ExportSpec("application/zip", "speaker_project.zip", lambda r, parts: project_zip(r, parts)),
    }


def register_exporter(fmt: str, spec: ExportSpec) -> None:
    """Extension point for adding new CNC/CAD/documentation export formats."""
    EXPORTERS[fmt] = spec


def _feat(op, x, y, d, depth=None, label=None):
    return {"op": op, "x": round(x, 2), "y": round(y, 2), "d": round(d, 2), "depth": depth, "label": label}


def _driver_features(drv, p, role, baffle_t):
    out = [_feat("through", p["x"], p["y"], drv.cutout_d_mm, baffle_t, f"{role} cut-out"),
           _feat("pocket", p["x"], p["y"], drv.outer_d_mm + 1.0, round(drv.flange_mm, 1), f"{role} flush rebate"),
           _feat("center", p["x"], p["y"], 10, None, role)]
    if role.startswith("woofer") or role == "mid":
        out.append(_feat("chamfer_rear", p["x"], p["y"], drv.cutout_d_mm + 2 * baffle_t * 0.8, None, "45deg rear chamfer"))
    bc = drv.effective_bolt_circle
    for i in range(drv.bolt_count):
        a = math.pi / 2 + (i + 0.5) * 2 * math.pi / drv.bolt_count
        out.append(_feat("drill", p["x"] + bc / 2 * math.cos(a), p["y"] + bc / 2 * math.sin(a), 3.0, 15, "pilot"))
    return out


def build_parts(result: dict, drivers: dict) -> list[dict]:
    """drivers: {"woofer": Driver, "mid": Driver|None, "tweeter": Driver}"""
    g = result["geometry"]
    d = result["design"]
    pos = d["layout"]["positions"]
    port = result["port"]
    ch = result["chamber"]
    W, M, T = drivers["woofer"], drivers["mid"], drivers["tweeter"]
    bt = g["baffle_t"]
    feats = []
    for i, p in enumerate(pos["woofer"]):
        feats += _driver_features(W, p, f"woofer{i + 1}", bt)
    if M:
        feats += _driver_features(M, pos["mid"], "mid", bt)
    if T:
        feats += _driver_features(T, pos["tweeter"], "tweeter", bt)
    back_feats = []
    if port and port["shape"] == "round":
        for i, p in enumerate(pos.get("port", [])):
            if port["location"] == "front":
                feats.append(_feat("through", p["x"], p["y"], port["outer_d_mm"] + 0.5, bt, f"port{i + 1} (tube OD)"))
                feats.append(_feat("center", p["x"], p["y"], 10, None, "port"))
            elif port["location"] == "rear":
                back_feats.append(_feat("through", g["baffle_w"] - p["x"] - g["open_x"], p["y"] - g["open_y"],
                                        port["outer_d_mm"] + 0.5, g["back_t"], f"port{i + 1}"))
    elif port and port["shape"] == "slot" and port["location"] == "front":
        feats.append({"op": "rect", "x": g["open_x"] + (g["open_w"] - port["slot_w_mm"]) / 2, "y": g["open_y"],
                      "w": port["slot_w_mm"], "h": port["slot_h_mm"], "label": "slot port opening"})
    parts = []
    parts.append({"name": "Front baffle LEFT", "qty": 1, "w": g["baffle_w"], "h": g["baffle_h"], "t": bt,
                  "material": "MDF", "features": feats, "notes": "Seen from the front. Rebates on the front face."})
    mirrored = [({**f, "x": round(g["baffle_w"] - f["x"] - (f.get("w", 0) if f["op"] == "rect" else 0), 2)}) for f in feats]
    parts.append({"name": "Front baffle RIGHT", "qty": 1, "w": g["baffle_w"], "h": g["baffle_h"], "t": bt,
                  "material": "MDF", "features": mirrored, "notes": "Mirror of left: tweeter on the inner (left) side."})
    term = {"op": "rect", "x": 0, "y": 0, "w": 80, "h": 80, "label": "terminal plate cut-out"}
    if g["mode"] == "fit":
        if g["back_mode"] == "replace_inside":
            bw, bh = g["int_w"] - 1, g["int_h"] - 1
        else:
            bw, bh = g["outer_w"], g["outer_h"]
    else:
        bw, bh = g["int_w"], g["int_h"]
    term.update(x=round(bw / 2 - 40, 1), y=round(min(60, bh / 4), 1))
    if g["back_mode"] not in ("keep", "solid") or g["mode"] != "fit":
        parts.append({"name": "Back panel", "qty": 2, "w": bw, "h": bh, "t": 18, "material": "MDF",
                      "features": back_feats + [term], "notes": "Seen from inside. Glue + screw, seal edges airtight."})
    if port and port["location"] == "bottom":
        hf = [_feat("through", p["x"], p["z"], port["outer_d_mm"] + 0.5, None, f"port{i + 1} (tube OD)")
              for i, p in enumerate(pos.get("port", []))]
        hf += [_feat("center", p["x"], p["z"], 10, None, "port") for p in pos.get("port", [])]
        parts.append({"name": "Bottom drilling template", "qty": 2, "w": g["int_w"], "h": g["int_d"], "t": g["wall_t"],
                      "material": "existing bottom", "features": hf, "template": True,
                      "notes": "Interior plan view: x from LEFT inner wall, y = depth from the baffle. Mirror X for the right cabinet."})
    if g["mode"] == "free":
        parts += [
            {"name": "Side panel", "qty": 4, "w": g["outer_d"] - 2 * g["wall_t"], "h": g["outer_h"], "t": g["wall_t"], "material": "MDF", "features": []},
            {"name": "Top / bottom panel", "qty": 4, "w": g["int_w"], "h": g["outer_d"] - 2 * g["wall_t"], "t": g["wall_t"], "material": "MDF", "features": []},
        ]
    if ch:
        iw, ih, cd, cw = ch["inner_w"], ch["inner_h"], ch["inner_depth"], ch["wall"]
        parts += [
            {"name": "Mid chamber back", "qty": 2, "w": iw + 2 * cw, "h": ih + 2 * cw, "t": cw, "material": "MDF 12 mm",
             "features": [_feat("drill", (iw + 2 * cw) / 2, (ih + 2 * cw) / 2, 8, cw, "cable hole (seal!)")]},
            {"name": "Mid chamber side", "qty": 4, "w": cd, "h": ih + 2 * cw, "t": cw, "material": "MDF 12 mm", "features": []},
            {"name": "Mid chamber top/bottom", "qty": 4, "w": cd, "h": iw, "t": cw, "material": "MDF 12 mm", "features": []},
        ]
    parts.append({"name": "Baffle-to-back brace", "qty": 4, "w": g["int_d"], "h": 36, "t": 18, "material": "MDF",
                  "features": [], "notes": "Glue between baffle and back where free (2 per cabinet)."})
    if port and port["shape"] == "round":
        parts.append({"name": f"Port tube: {port.get('tube_name') or 'ID %.0f mm' % port['d_mm']}", "qty": 2 * port["count"], "w": port["length_mm"],
                      "h": port["outer_d_mm"], "t": 0, "material": "HT/KG drain pipe (EN 1451) or flared port kit", "features": [],
                      "notes": f"Cut to {port['length_mm']:.0f} mm, flare/round the inner end."})
    elif port and port["shape"] == "slot":
        parts.append({"name": "Slot port shelf", "qty": 2, "w": port["length_mm"], "h": port["slot_w_mm"], "t": 18,
                      "material": "MDF", "features": [], "notes": f"Fixed {port['slot_h_mm']:.0f} mm above the floor, plus 2 side cheeks."})
    return parts


def _ops_summary(p):
    c: dict[str, int] = {}
    for f in p["features"]:
        c[f["op"]] = c.get(f["op"], 0) + 1
    return ", ".join(f"{v}x {k}" for k, v in c.items() if k != "center")


def cutlist_csv(parts: list[dict]) -> str:
    buf = io.StringIO()
    wr = csv.writer(buf)
    wr.writerow(["Part", "Qty (pair)", "Length/Width mm", "Height mm", "Thickness mm", "Material", "Operations", "Notes"])
    for p in parts:
        wr.writerow([p["name"], p["qty"], round(p["w"], 1), round(p["h"], 1), p["t"], p["material"], _ops_summary(p), p.get("notes", "")])
    return buf.getvalue()


def _layer_for(f):
    if f["op"] == "through" or f["op"] == "rect":
        return "CUT_THROUGH"
    if f["op"] == "pocket":
        return f"POCKET_{f['depth']:.1f}MM"
    if f["op"] == "drill":
        return f"DRILL_{f['d']:.1f}MM"
    if f["op"] == "chamfer_rear":
        return "CHAMFER_REAR"
    return "CENTER"


def dxf_bytes(parts: list[dict], gap: float = 40.0) -> bytes:
    doc = ezdxf.new("R2010", setup=True)
    doc.header["$INSUNITS"] = 4  # mm
    msp = doc.modelspace()

    def layer(name):
        if name not in doc.layers:
            base = name.split("_")[0] if name.split("_")[0] in LAYERS else name
            doc.layers.add(name, color=LAYERS.get(base, LAYERS.get(name, 7)))
        return name

    ox = 0.0
    for p in parts:
        if p.get("t", 0) == 0:
            continue
        w, h = p["w"], p["h"]
        msp.add_lwpolyline([(ox, 0), (ox + w, 0), (ox + w, h), (ox, h)], close=True, dxfattribs={"layer": layer("OUTLINE")})
        for f in p["features"]:
            ly = layer(_layer_for(f))
            if f["op"] == "rect":
                x, y = ox + f["x"], f["y"]
                msp.add_lwpolyline([(x, y), (x + f["w"], y), (x + f["w"], y + f["h"]), (x, y + f["h"])], close=True,
                                   dxfattribs={"layer": ly})
            elif f["op"] == "center":
                r = f["d"] / 2
                msp.add_line((ox + f["x"] - r, f["y"]), (ox + f["x"] + r, f["y"]), dxfattribs={"layer": ly})
                msp.add_line((ox + f["x"], f["y"] - r), (ox + f["x"], f["y"] + r), dxfattribs={"layer": ly})
            else:
                msp.add_circle((ox + f["x"], f["y"]), f["d"] / 2, dxfattribs={"layer": ly})
        msp.add_text(f"{p['name']} x{p['qty']}  {w:.1f} x {h:.1f} x {p['t']} {p['material']}",
                     dxfattribs={"layer": layer("TEXT"), "height": 8}).set_placement((ox, h + 10))
        ox += w + gap
    buf = io.StringIO()
    doc.write(buf)
    return buf.getvalue().encode()


def svg_part(p: dict, pad: float = 20.0) -> str:
    w, h = p["w"], p["h"]
    W, H = w + 2 * pad, h + 2 * pad + 20

    def Y(y):  # flip: SVG y grows downward
        return pad + 20 + (h - y)

    el = [f'<rect x="{pad}" y="{pad + 20}" width="{w}" height="{h}" fill="none" stroke="#000" stroke-width="0.4"/>']
    colors = {"through": "#d00", "pocket": "#00c", "drill": "#080", "chamfer_rear": "#a0a", "center": "#888", "rect": "#d00"}
    for f in p["features"]:
        c = colors.get(f["op"], "#000")
        dash = ' stroke-dasharray="3 2"' if f["op"] in ("pocket", "chamfer_rear") else ""
        if f["op"] == "rect":
            el.append(f'<rect x="{pad + f["x"]}" y="{Y(f["y"] + f["h"])}" width="{f["w"]}" height="{f["h"]}" fill="none" stroke="{c}" stroke-width="0.4"/>')
        elif f["op"] == "center":
            r = f["d"] / 2
            x, y = pad + f["x"], Y(f["y"])
            el.append(f'<path d="M{x - r},{y}H{x + r}M{x},{y - r}V{y + r}" stroke="{c}" stroke-width="0.3"/>')
        else:
            el.append(f'<circle cx="{pad + f["x"]}" cy="{Y(f["y"])}" r="{f["d"] / 2}" fill="none" stroke="{c}" stroke-width="0.4"{dash}/>')
    el.append(f'<text x="{pad}" y="{pad + 8}" font-size="7" font-family="sans-serif">{p["name"]} - {w:.1f} x {h:.1f} x {p["t"]} mm '
              f'(1:1 - print at 100 %; red=through, blue=rebate, green=pilot, purple=rear chamfer)</text>')
    return (f'<svg xmlns="http://www.w3.org/2000/svg" width="{W}mm" height="{H}mm" viewBox="0 0 {W} {H}">'
            + "".join(el) + "</svg>")


def build_notes(result: dict, parts: list[dict]) -> str:
    m = result["metrics"]
    d = result["design"]
    dr = result["drivers"]
    port = result["port"]
    g = result["geometry"]
    L = [f"# Build sheet - {d.get('name', 'speaker')}", ""]
    L.append(f"Drivers per speaker: {d['drivers']['woofer'].get('count', 1)}x {dr['woofer']['brand']} {dr['woofer']['model']}, "
             + (f"{dr['mid']['brand']} {dr['mid']['model']}, " if dr["mid"] else "")
             + (f"{dr['tweeter']['brand']} {dr['tweeter']['model']}" if dr["tweeter"] else "(subwoofer)"))
    L.append(f"Box: {m['box_type']}, net {m['net_volume_L']} L" + (f", tuned to {m['fb_hz']} Hz" if m["fb_hz"] else f", Qtc {m['qtc']}"))
    L.append(f"Woofer F3 {m['woofer_f3_hz']} Hz (anechoic, before room gain); max SPL @40 Hz {m['max_spl_40hz']} dB")
    xc = d.get("crossover")
    if result.get("system") == "sub":
        L.append(f"Subwoofer filters: low-pass {m['lp_hz']:.0f} Hz {d['sub']['lp_kind']}"
                 + (f", subsonic high-pass {m['subsonic_hz']:.0f} Hz" if m.get("subsonic_hz") else "") + f"; amplifier up to {m['amp_w']:.0f} W")
    elif xc:
        L.append(f"Crossover: {xc['mode']} {xc['kind']} at " + (f"{xc['f_wm']:.0f} Hz / " if xc["f_wm"] else "") + f"{xc['f_mt']:.0f} Hz; "
                 f"levels (dB cut) {xc['levels']}; polarity {xc['polarity']}")
    if port:
        L.append(f"Port: {port['count']}x {port['shape']} {port['location']}, "
                 + (f"{port.get('tube_name') or ''} ID {port['d_mm']:.1f} mm" if port["shape"] == "round" else f"{port['slot_w_mm']:.0f} x {port['slot_h_mm']:.0f} mm")
                 + f", length {port['length_mm']:.0f} mm, peak air speed {port['vel_peak_ms']} m/s")
    L += ["", "## Steps", ""]
    steps = []
    if g["mode"] == "fit":
        steps += ["Remove the doors and hinges; fill hinge holes with wood filler/epoxy so the cavity is airtight.",
                  "Seal every internal corner of the compartment with acrylic sealant or PU glue.",
                  {"replace_inside": "Glue + screw the new 18 mm MDF back panel inside, directly against the existing back; seal its perimeter.",
                   "replace_outside": "Replace the existing back with 18 mm MDF screwed + glued to the carcass from behind.",
                   "solid": "Check the existing back is airtight: seal all joints and holes with acrylic sealant.",
                   "keep": "WARNING: thin back retained - expect leaks and panel resonance."}[g["back_mode"]]]
    steps += ["CNC the baffles from the DXF: CUT_THROUGH (full depth), POCKET_x.xMM (flush rebates, front face), "
              "DRILL (pilot holes), CHAMFER_REAR (45 deg on the back face behind woofer/mid to unchoke the cone).",
              "Round over the baffle front edges (r >= 10 mm reduces diffraction ripple), unless flush with surrounding furniture."]
    if result["chamber"]:
        steps.append(f"Build the sealed mid chamber (inner {result['chamber']['inner_w']:.0f} x {result['chamber']['inner_h']:.0f} x "
                     f"{result['chamber']['inner_depth']:.0f} mm), glue it to the baffle back, fill it loosely with wool/polyester.")
    if port and port["location"] == "bottom":
        steps.append("Drill the bottom with a hole saw at the template position; glue the tube vertically. Keep >= one port diameter of free air below the cabinet.")
    steps += ["Line side/top/bottom walls with 20-30 mm acoustic foam or felt" + (" (keep the port mouth free)." if port else "; fill sealed volume ~50-80 % with polyester wool."),
              ("Fit the plate amplifier in the back-panel cut-out and seal it." if result.get("system") == "sub"
               else "Install terminals (active: 3 pairs per speaker, one per way) and seal cable holes."),
              "Fit the baffle on a 3 mm foam gasket and screw it to the carcass edges every ~100 mm (removable for service).",
              ("Measure at the listening seat (REW + calibrated mic), then set phase, low-pass and level." if result.get("system") == "sub"
               else "Measure in room (REW + calibrated mic), then refine crossover levels/EQ.")]
    L += [f"{i + 1}. {s}" for i, s in enumerate(steps)]
    sol = result.get("soldering") or {}
    if result.get("crossover_parts"):
        L += ["", "## Crossover parts per speaker" + (" - SOLDERING REQUIRED" if sol.get("required") else ""), ""]
        for role, b in result["crossover_parts"].items():
            L.append(f"**{role}** (polarity {'normal' if b.get('polarity', 1) > 0 else 'INVERTED: swap + and - at the driver'})")
            if b.get("purpose"):
                L.append(f"  {b['purpose']}")
            for p in b["parts"]:
                L.append(f"- {p['ref']} {p['type']} {p['value']:g} {p['unit']} -> buy: {p['build']} ({p['spec']}), {p['position']}, ~EUR {p['est_eur']:.2f}")
        L += ["", f"Soldering: {sol.get('components_incl_parallel', 0)} components, ~{sol.get('solder_joints_est', 0)} solder joints per speaker.", ""]
        L += [f"- {s_}" for s_ in sol.get("steps", [])]
        L += ["", "Tools: " + ", ".join(sol.get("tools", []))]
    if result.get("notes"):
        L += ["", "## Notes", ""] + [f"- {n}" for n in result["notes"]]
    if result["warnings"]:
        L += ["", "## Warnings", ""] + [f"- {w}" for w in result["warnings"]]
    L += ["", "## Cut list", "", "| Part | Qty (pair) | W x H x T mm | Material |", "|---|---|---|---|"]
    L += [f"| {p['name']} | {p['qty']} | {p['w']:.1f} x {p['h']:.1f} x {p['t']} | {p['material']} |" for p in parts]
    return "\n".join(L) + "\n"


def project_zip(result: dict, parts: list[dict]) -> bytes:
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as z:
        z.writestr("all_panels.dxf", dxf_bytes(parts))
        for p in parts:
            if p.get("t", 0) == 0:
                continue
            slug = p["name"].lower().replace(" ", "_").replace("/", "-")
            z.writestr(f"dxf/{slug}.dxf", dxf_bytes([p]))
            z.writestr(f"svg/{slug}.svg", svg_part(p))
        z.writestr("cutlist.csv", cutlist_csv(parts))
        z.writestr("BUILD.md", build_notes(result, parts))
        z.writestr("design.json", json.dumps(result["design"], indent=1))
    return buf.getvalue()


EXPORTERS: dict[str, ExportSpec] = _build_exporters()
