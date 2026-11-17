import io
import zipfile

import ezdxf
from fastapi.testclient import TestClient

from app.main import app

c = TestClient(app)


def test_default_design_simulates_and_fits():
    r = c.post("/api/simulate", json={}).json()
    m = r["metrics"]
    assert m["ways"] == 3
    assert 40 < m["net_volume_L"] < 70
    assert m["woofer_f3_hz"] < 45
    assert not [w for w in r["warnings"] if "overlap" in w or "exceeds baffle" in w]
    assert len(r["curves"]["f"]) == len(r["curves"]["sum"])


def test_passive_and_bottom_port():
    r = c.post("/api/simulate", json={"crossover": {"mode": "passive"}, "box": {"port": {"location": "bottom"}}}).json()
    assert r["crossover_parts"]["woofer"]["parts"]
    assert r["port"]["location"] == "bottom" and r["design"]["layout"]["positions"]["port"]
    assert r["metrics"]["z_min_ohm"] > 2


def test_optimizer_respects_budget():
    r = c.post("/api/optimize", json={"budget_eur_pair": 500, "top_n": 3}).json()
    assert r["results"]
    assert all(x["metrics"]["price_drivers_pair_eur"] <= 500 for x in r["results"])


def test_reverse_builds_box():
    r = c.post("/api/reverse", json={"woofer": "dayton-rs225-8", "mid": "sb-sb15mfc30-8", "tweeter": "sb-sb26adc-c000-4"}).json()
    g = r["result"]["geometry"]
    assert g["mode"] == "free" and g["outer_h"] > g["outer_w"]
    assert abs(r["result"]["metrics"]["net_volume_L"] - r["net_target_L"]) < 1.5


def test_exports():
    dxf = c.post("/api/export/dxf", json={}).content
    doc = ezdxf.read(io.StringIO(dxf.decode()))
    layers = {l.dxf.name for l in doc.layers}
    assert "CUT_THROUGH" in layers and any(n.startswith("POCKET_") for n in layers)
    z = zipfile.ZipFile(io.BytesIO(c.post("/api/export/zip", json={}).content))
    assert {"cutlist.csv", "BUILD.md", "design.json", "all_panels.dxf"} <= set(z.namelist())


def test_custom_driver_roundtrip(tmp_path, monkeypatch):
    monkeypatch.setenv("CUSTOM_DRIVERS_PATH", str(tmp_path / "c.json"))
    d = {"id": "my-w", "brand": "Me", "model": "W1", "role": "woofer", "nominal_mm": 200, "price_eur": 10, "Re": 6, "Le_mH": 0.5,
         "Fs": 30, "Qms": 4, "Qes": 0.4, "Vas_L": 50, "Sd_cm2": 210, "sens_db": 88, "Z_nom": 8, "outer_d_mm": 220,
         "cutout_d_mm": 185, "depth_mm": 90}
    assert c.post("/api/drivers", json=d).status_code == 200
    assert any(x["id"] == "my-w" for x in c.get("/api/drivers").json())
    assert c.delete("/api/drivers/my-w").status_code == 200


def test_bad_driver_is_400():
    assert c.post("/api/simulate", json={"drivers": {"woofer": {"id": "nope"}}}).status_code == 400


def test_index_and_plotly_served():
    assert c.get("/").status_code == 200
    assert c.get("/vendor/plotly.min.js").status_code == 200


def test_active_lr4_sum_is_coherent():
    """Regression: path-delay phase used mm with k in rad/m, producing a comb filter in the sum."""
    r = c.post("/api/simulate", json={"crossover": {"mode": "active", "tweeter_protect": False}}).json()
    assert r["design"]["crossover"]["polarity"] == {"woofer": 1, "mid": 1, "tweeter": 1}
    assert r["metrics"]["deviation_db"] < 3.5


def test_default_layout_keeps_min_mdf_web():
    r = c.post("/api/simulate", json={}).json()
    assert min(x["web_mm"] for x in r["clearances"]) >= 10 - 0.05
    assert not [w for w in r["warnings"] if "MDF" in w or "overlap" in w]


def test_overlap_is_reported():
    r = c.post("/api/simulate", json={}).json()
    pos = r["design"]["layout"]["positions"]
    pos["tweeter"] = {"x": pos["mid"]["x"], "y": pos["mid"]["y"] + 80}
    r2 = c.post("/api/simulate", json={"layout": {"positions": pos}}).json()
    assert any("overlaps" in w for w in r2["warnings"])


def test_passive_bom_is_buildable_and_soldering_flagged():
    r = c.post("/api/simulate", json={"crossover": {"mode": "passive"}}).json()
    assert r["soldering"]["required"] and r["soldering"]["solder_joints_est"] > 10
    for b in r["crossover_parts"].values():
        for p in b["parts"]:
            assert p["est_eur"] > 0
            if p["type"] != "inductor":
                assert p["build_error_pct"] <= 12
            else:
                assert p["use_value"] >= p["value"] * 0.97  # coils rounded up (unwind to tune)


def test_no_imperial_units_in_driver_db():
    ds = c.get("/api/drivers").json()
    assert len(ds) > 1000
    for d in ds:
        assert "size_in" not in d and d["nominal_mm"] > 0
        if d.get("price_eur", 0) > 0:
            assert d["shop"]["price_eur"] > 0


def test_tune_improves_and_respects_tweeter_limit():
    for mode in ("active", "passive"):
        r = c.post("/api/tune", json={"crossover": {"mode": mode}}).json()
        assert r["after"]["score"] <= r["before"]["score"] + 1e-6
        k = 2.5 if mode == "active" else 3.0
        assert r["design"]["crossover"]["f_mt"] >= 680 * k - 1  # SB26ADC Fs = 680 Hz


def test_potential_lists_fitting_woofers():
    p = c.post("/api/potential", json={"cabinet": {}}).json()
    assert p["woofers"] and p["best"]["vented_f3"] < 40
    assert all(w["nominal_mm"] <= p["fit"]["max_frame_mm"] for w in p["woofers"])


def test_mid_chamber_collision_is_an_error():
    r = c.post("/api/simulate", json={}).json()
    pos, port = r["design"]["layout"]["positions"], r["port"]
    m = pos["mid"]
    pos["port"] = [{"x": m["x"], "y": m["y"] - 75 - port["outer_d_mm"] / 2 - 14}]
    chk = c.post("/api/layout/check", json={"design": {"layout": {"positions": pos}}, "port": port}).json()
    assert not chk["ok"] and any("mid chamber collides" in e for e in chk["errors"])


def test_web_below_minimum_is_rejected():
    r = c.post("/api/simulate", json={}).json()
    pos = r["design"]["layout"]["positions"]
    web = next(x["web_mm"] for x in r["clearances"] if {x["a"], x["b"]} == {"mid", "tweeter"})
    pos["tweeter"]["y"] -= web - 4  # leave only 4 mm of MDF
    chk = c.post("/api/layout/check", json={"design": {"layout": {"positions": pos}}, "port": r["port"]}).json()
    assert not chk["ok"] and any("MDF" in e for e in chk["errors"])


def test_maximize_improves_and_stays_buildable():
    r = c.post("/api/maximize", json={}).json()
    assert r["after"]["score"] <= r["before"]["score"]
    chk = c.post("/api/layout/check", json={"design": r["design"], "port": r["result"]["port"]}).json()
    assert chk["ok"], chk["errors"]


def test_drivers_stay_inside_dashed_cavity_line_and_woofer_cannot_cover_port():
    r = c.post("/api/simulate", json={"box": {"port": {"location": "front"}}}).json()
    pos, port, g = r["design"]["layout"]["positions"], r["port"], r["geometry"]
    w = pos["woofer"][0]
    assert w["x"] - r["drivers"]["woofer"]["outer_d_mm"] / 2 >= g["open_x"] + 2.9
    pos["woofer"][0] = dict(pos["port"][0])  # drop the woofer onto the port
    chk = c.post("/api/layout/check", json={"design": {"layout": {"positions": pos}}, "port": port}).json()
    assert not chk["ok"]


def test_maximize_keeps_everything_inside_the_opening():
    r = c.post("/api/maximize", json={"box": {"port": {"location": "front"}}}).json()
    g, pos, d = r["result"]["geometry"], r["design"]["layout"]["positions"], r["result"]["drivers"]
    for role, drv in (("mid", d["mid"]), ("tweeter", d["tweeter"])):
        p, rad = pos[role], drv["outer_d_mm"] / 2
        assert g["open_x"] + rad + 2.9 <= p["x"] <= g["open_x"] + g["open_w"] - rad - 2.9
        assert g["open_y"] + rad + 2.9 <= p["y"] <= g["open_y"] + g["open_h"] - rad - 2.9


def test_maximize_is_not_beaten_by_small_manual_nudges():
    import copy
    m = c.post("/api/maximize", json={"box": {"port": {"location": "front"}}}).json()
    best = m["result"]["metrics"]
    assert m["after"]["deviation_db"] < m["before"]["deviation_db"]
    assert m["after"]["sensitivity"] >= m["before"]["sensitivity"] - 0.5
    for role in ("woofer", "tweeter", "mid"):
        for dx, dy in ((-10, 0), (10, 0), (0, -10), (0, 10), (-5, -5), (5, 5)):
            d = copy.deepcopy(m["design"])
            p = d["layout"]["positions"][role]
            p = p[0] if isinstance(p, list) else p
            p["x"] += dx
            p["y"] += dy
            r = c.post("/api/simulate", json=d).json()
            if r["warnings"]:
                continue
            mt = r["metrics"]
            assert not (mt["deviation_db"] < best["deviation_db"] - 0.05 and
                        mt["sensitivity_db_2v83_1m"] > best["sensitivity_db_2v83_1m"] + 0.05), (role, dx, dy)


def _encloses(res):
    pos, ch = res["design"]["layout"]["positions"], res["chamber"]
    cx, cy = pos["mid"]["x"] + ch["offset_x"], pos["mid"]["y"] + ch["offset_y"]
    keep = ch["mid_cutout_mm"] / 2 + 6
    return abs(pos["mid"]["x"] - cx) <= ch["inner_w"] / 2 - keep + 0.6 and abs(pos["mid"]["y"] - cy) <= ch["inner_h"] / 2 - keep + 0.6


def test_mid_chamber_always_encloses_the_mid():
    r = c.post("/api/simulate", json={}).json()
    assert _encloses(r)
    m = c.post("/api/maximize", json={"box": {"port": {"location": "front"}}}).json()
    assert _encloses(m["result"]) and not m["result"]["warnings"]
    pos = r["design"]["layout"]["positions"]
    pos["tweeter"] = {"x": pos["mid"]["x"] - 96, "y": pos["mid"]["y"] - 74}  # the reported case: tweeter tucked below
    chk = c.post("/api/layout/check", json={"design": {"layout": {"positions": pos}}, "port": r["port"]}).json()
    assert not chk["ok"]


def test_measured_frd_and_zma_are_used(tmp_path, monkeypatch):
    import numpy as np
    monkeypatch.setenv("MEASUREMENTS_PATH", str(tmp_path))
    f = np.geomspace(20, 20000, 200)
    s = 1j * f / 1500
    db = 90 + 20 * np.log10(np.abs(s ** 2 / (s ** 2 + s / 0.7 + 1))) + 3 * np.exp(-((np.log2(f / 6000)) ** 2) * 8)  # +3 dB bump at 6 kHz
    frd = "\n".join(["* fake tweeter, Freq dB Phase"] + [f"{x:.2f} {y:.3f} 0" for x, y in zip(f, db)])
    zma = "\n".join(f"{x:.2f} {3.4 + 4 * np.exp(-((np.log2(x / 700)) ** 2) * 3):.3f} 0" for x in f)
    assert c.post("/api/drivers/sb-sb26adc-c000-4/measurements/frd", json={"text": frd}).status_code == 200
    assert c.post("/api/drivers/sb-sb26adc-c000-4/measurements/zma", json={"text": zma}).status_code == 200
    r = c.post("/api/simulate", json={}).json()
    assert r["measured"]["tweeter"] == ["response", "impedance"]
    ff = np.array(r["curves"]["f"]); raw = np.array(r["curves"]["spl_raw"]["tweeter"])
    bump = raw[np.argmin(abs(ff - 6000))] - raw[np.argmin(abs(ff - 3000))]
    assert bump > 1.5  # the measured bump shows up in the simulation
    assert any(d["id"] == "sb-sb26adc-c000-4" and "frd" in d["measured"] for d in c.get("/api/drivers").json())
    assert c.delete("/api/drivers/sb-sb26adc-c000-4/measurements/frd").json()["deleted"]


def test_ngspice_agrees_with_internal_network_solver():
    import shutil
    import pytest
    if not shutil.which("ngspice"):
        pytest.skip("ngspice not installed (runs in the Docker image)")
    q = c.post("/api/spice", json={"crossover": {"mode": "passive"}}).json()
    assert q["available"] and q["max_dev_db"] < 0.1 and "LCES" in q["netlist"]


def test_part_details_and_port_options():
    r = c.post("/api/simulate", json={"crossover": {"mode": "passive"}}).json()
    caps = [p for b in r["crossover_parts"].values() for p in b["parts"] if p["type"] == "capacitor"]
    assert all(any("100 V" in d for d in p["details"]) and any("polar" in d.lower() for d in p["details"]) for p in caps)
    o = c.post("/api/port/options", json={"box": {"port": {"location": "front"}}}).json()
    assert o and o[0]["vel_peak_ms"] <= o[-1]["vel_peak_ms"] and all(p["fits"] for p in o)


def test_enclosure_from_two_to_five_drivers_is_buildable():
    for n, mid in ((1, None), (1, "sb-sb15mfc30-8"), (2, None), (2, "sb-sb15mfc30-8"), (3, "sb-sb15mfc30-8")):
        q = c.post("/api/reverse", json={"woofer": "dayton-rs225-8", "woofer_count": n, "mid": mid,
                                         "tweeter": "sb-sb26adc-c000-4", "alignment": "auto", "layout_style": "auto"}).json()
        r = q["result"]
        assert not [w for w in r["warnings"] if "dashed" in w or "chamber" in w or "overlap" in w], (n, mid, r["warnings"])
        assert r["metrics"]["woofer_f3_hz"] < 40


def test_subwoofer_design_simulates_and_exports():
    q = c.post("/api/sub/reverse", json={"woofer": "dayton-rss265hf-4", "woofer_count": 1, "alignment": "auto"}).json()
    r = q["result"]
    m = r["metrics"]
    assert r["system"] == "sub" and r["drivers"]["tweeter"] is None
    assert m["woofer_f3_hz"] < 30 and m["xmax_use_pct"] <= 102 and not r["warnings"]
    assert m["amp_w"] <= m["rated_power_w"]
    for fmt in ("parts", "dxf", "cutlist", "build", "zip"):
        assert c.post(f"/api/export/{fmt}", json=r["design"]).status_code == 200
    s = c.post("/api/sub/simulate", json={**r["design"], "sub": {**r["design"]["sub"], "amp_w": 1000}}).json()
    assert any("Xmax" in w for w in s["warnings"])


def test_driver_base_search_replacements_and_price_parser(tmp_path, monkeypatch):
    from app.design.catalog import parse_shop_html
    html = '<script type="application/ld+json">{"@type":"Product","sku":"SB23NRXS45-8","offers":{"price":"113.95","priceCurrency":"EUR","availability":"https://schema.org/InStock"}}</script>'
    parsed = parse_shop_html("https://www.soundimports.eu/en/test.html", html)
    assert parsed["price_eur"] == 113.95 and parsed["in_stock"] and parsed["sku"] == "SB23NRXS45-8"

    res = c.get("/api/driver-base/search?q=SB23NACS45-8").json()
    assert any(d["model"] == "SB23NACS45-8" and (d.get("shop") or {}).get("url") for d in res)

    rep = c.get("/api/drivers/sb-sb23nrxs45-8/replacements?limit=5").json()
    assert rep["replacements"] and rep["replacements"][0]["match_pct"] >= 85
    assert any("NACS45" in r["model"] or "NBACS45" in r["model"] for r in rep["replacements"])

    imp = c.post("/api/driver-base/import", json={"id": rep["replacements"][0]["id"], "fetch_price": False})
    assert imp.status_code == 200 and imp.json()["id"] == rep["replacements"][0]["id"]
    assert len(c.get("/api/drivers").json()) > 1000
    assert "NACS45" in open("app/data/drivers.json").read()
