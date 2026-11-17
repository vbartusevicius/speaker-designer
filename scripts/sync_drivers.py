#!/usr/bin/env python3
"""Sync the unified driver catalog (app/data/drivers.json) from driver-base (CC BY 4.0)
and match SoundImports (EU) product URLs from their sitemap.

Preserves existing curated drivers, custom notes, and previously fetched shop prices/stock,
writing readable indent=2 JSON.

Usage:
  python scripts/sync_drivers.py             # update app/data/drivers.json from driver-base + sitemap
  python scripts/sync_drivers.py --prices    # also refresh live EUR prices & stock for curated drivers
"""
from __future__ import annotations

import argparse
import json
import math
import re
import sys
import time
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
DRIVERS_PATH = ROOT / "app" / "data" / "drivers.json"
DRIVER_BASE_URL = "https://raw.githubusercontent.com/JonathanDCohen/driver-base/main/web/drivers.json"
SOUNDIMPORTS_SITEMAP = "https://www.soundimports.eu/en/sitemap.xml"
UA = "Mozilla/5.0 (compatible; SpeakerDesignerSync/1.0)"


def fetch_text(url: str, timeout: float = 30.0) -> str:
    req = urllib.request.Request(url, headers={"User-Agent": UA})
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        return resp.read().decode("utf-8", "ignore")


def _norm_key(brand: str, model: str) -> str:
    return re.sub(r"[^a-z0-9]+", "", f"{brand}{model}".lower())


def map_role(d: dict) -> str | None:
    kind = d.get("driver_kind")
    if kind == "tweeter":
        return "tweeter"
    if kind == "fullrange":
        sz = d.get("nominal_size_mm") or 0
        return "mid" if sz <= 140 else "midwoofer"
    if kind == "lf_woofer":
        fs = d.get("fs_hz") or 999
        sz = d.get("nominal_size_mm") or 0
        fmax = d.get("freq_high_hz") or 0
        xmax = d.get("xmax_mm") or 0
        if fs <= 32 and (sz >= 240 or xmax >= 10):
            return "subwoofer"
        if sz <= 145 and fs >= 55:
            return "mid"
        if sz <= 185 and (fmax == 0 or fmax >= 2000):
            return "midwoofer"
        return "woofer"
    return None


def load_soundimports_slugs() -> list[tuple[str, str, str]]:
    sm = fetch_text(SOUNDIMPORTS_SITEMAP)
    locs = re.findall(r"<loc>([^<]+)</loc>", sm)
    urls: list[str] = []
    for u in locs:
        if "sitemap" in u:
            urls.extend(re.findall(r"<loc>([^<]+)</loc>", fetch_text(u)))
        else:
            urls.append(u)
    slug_items: list[tuple[str, str, str]] = []
    for u in urls:
        m = re.match(r"https://www\.soundimports\.eu/en/([a-z0-9-]+)\.html$", u)
        if m:
            sl = m.group(1)
            slug_items.append((re.sub(r"[^a-z0-9]+", "", sl), sl, u))
    return slug_items


def sync_catalog(dry_run: bool = False) -> tuple[int, int]:
    existing_raw = json.loads(DRIVERS_PATH.read_text()) if DRIVERS_PATH.exists() else {"drivers": []}
    existing_list = existing_raw.get("drivers", [])
    existing_by_key = {_norm_key(d.get("brand", ""), d.get("model", "")): d for d in existing_list}

    curated = [d for d in existing_list if d.get("curated")]
    merged: list[dict] = [dict(d) for d in curated]
    seen = {_norm_key(d.get("brand", ""), d.get("model", "")) for d in merged}

    raw = json.loads(fetch_text(DRIVER_BASE_URL))
    slug_items = load_soundimports_slugs()

    for d in raw["drivers"]:
        if d.get("status") != "active":
            continue
        role = map_role(d)
        if not role:
            continue
        fs, re_ = d.get("fs_hz"), d.get("re_ohm")
        if not fs or not re_:
            continue
        if role != "tweeter" and not (d.get("qts") and d.get("vas_liters") and d.get("sd_cm2")):
            continue
        brand = (d.get("manufacturer") or "").strip()
        model = (d.get("model") or "").strip()
        if not brand or not model:
            continue
        key = _norm_key(brand, model)
        if key in seen:
            continue
        seen.add(key)

        b_norm = re.sub(r"[^a-z0-9]+", "", brand.lower())
        m_slug = re.sub(r"[^a-z0-9]+", "-", model.lower()).strip("-")
        m_norm = re.sub(r"[^a-z0-9]+", "", model.lower())
        shop_url = None
        if len(m_norm) >= 4:
            pat = re.compile(r"(?:^|-)" + re.escape(m_slug) + r"(?:-|$)")
            for n_sl, sl, u in slug_items:
                if m_norm in n_sl and (b_norm[:4] in n_sl or pat.search(sl)):
                    if n_sl.endswith(m_norm) or pat.search(sl):
                        shop_url = u
                        break

        nom = d.get("nominal_size_mm") or (28 if role == "tweeter" else 165)
        sd = d.get("sd_cm2") or (5.5 if role == "tweeter" else round(math.pi * (nom * 0.42 / 10) ** 2, 1))
        outer = d.get("overall_diameter_mm")
        cutout = d.get("mounting_diameter_mm")
        depth = d.get("depth_mm")
        dims_verified = bool(outer and cutout and depth)
        if not outer:
            outer = round(nom * 1.03 if role != "tweeter" else 104, 1)
        if not cutout:
            cutout = round(outer * 0.87, 1)
        if not depth:
            depth = round(outer * 0.43 if role != "tweeter" else 30.0, 1)
        sens = d.get("sensitivity_db_2_83v_1m") or d.get("sensitivity_db_1w_1m") or 88.0
        z_nom = d.get("impedance_nominal_ohm") or (4 if re_ < 5 else 8)
        pe = d.get("power_long_term_watts") or d.get("power_aes_watts") or (80 if role != "tweeter" else 60)

        prev = existing_by_key.get(key) or {}
        prev_shop = prev.get("shop") or {}
        src = (d.get("source_urls") or [None])[0]

        rec: dict = {
            "id": prev.get("id") or ("db-" + re.sub(r"[^a-z0-9]+", "-", f"{brand}-{model}".lower()).strip("-")),
            "brand": brand,
            "model": model,
            "role": role,
            "nominal_mm": round(float(nom), 1),
            "Re": round(float(re_), 2),
            "Le_mH": round(float(d.get("le_mh") or (0.05 if role == "tweeter" else 0.5)), 3),
            "Fs": round(float(fs), 1),
            "Qms": round(float(d.get("qms") or 3.0), 2),
            "Qes": round(float(d.get("qes") or (d.get("qts") or 0.5)), 3),
            "Qts": round(float(d.get("qts") or 0.5), 3),
            "Vas_L": round(float(d.get("vas_liters") or 0.0), 2) if role != "tweeter" else None,
            "Sd_cm2": round(float(sd), 1),
            "Xmax_mm": round(float(d.get("xmax_mm") or (0.5 if role == "tweeter" else 4.0)), 2),
            "Pe_W": round(float(pe), 0),
            "sens_db": round(float(sens), 1),
            "Z_nom": round(float(z_nom), 1),
            "outer_d_mm": round(float(outer), 1),
            "cutout_d_mm": round(float(cutout), 1),
            "depth_mm": round(float(depth), 1),
            "flange_mm": 6.0 if role != "tweeter" else 4.0,
            "bolt_circle_mm": round(float((outer + cutout) / 2), 1),
            "bolt_count": 4 if role == "tweeter" else (8 if nom >= 210 else 6),
            "fmin": round(float(d.get("freq_low_hz") or (1500 if role == "tweeter" else fs)), 0),
            "fmax": round(float(d.get("freq_high_hz") or (22000 if role == "tweeter" else 3500)), 0),
            "dims_verified": dims_verified,
            "verified": True,
            "curated": False,
            "price_eur": float(prev.get("price_eur") or 0.0),
            "notes": f"From driver-base (CC BY 4.0){' · ' + src if src else ''}.",
        }
        if shop_url or prev_shop.get("url"):
            rec["shop"] = {
                "name": prev_shop.get("name", "SoundImports (NL)"),
                "url": shop_url or prev_shop.get("url"),
                "price_eur": float(prev_shop.get("price_eur") or 0.0),
                "in_stock": bool(prev_shop.get("in_stock", True)),
                "checked": prev_shop.get("checked", ""),
            }
        if d.get("mms_g"):
            rec["Mms_g"] = round(float(d["mms_g"]), 2)
        if d.get("bl_tm"):
            rec["Bl"] = round(float(d["bl_tm"]), 2)
        merged.append(rec)

    eu_count = sum(1 for r in merged if (r.get("shop") or {}).get("url"))
    if not dry_run:
        DRIVERS_PATH.write_text(json.dumps({
            "_note": "Unified EU loudspeaker driver catalog (T/S datasheet specs + SoundImports EUR prices). Derived entries from driver-base (CC BY 4.0). dims_verified=false means frame dimensions are estimates.",
            "_synced_at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
            "drivers": merged,
        }, indent=2) + "\n")
    return len(merged), eu_count


def sync_curated_prices(delay: float = 2.0, dry_run: bool = False) -> tuple[int, int]:
    sys.path.insert(0, str(ROOT))
    from app.design.catalog import parse_shop_html

    data = json.loads(DRIVERS_PATH.read_text())
    updated, failed = 0, 0
    for d in data["drivers"]:
        if not d.get("curated"):
            continue
        url = (d.get("shop") or {}).get("url")
        if not url:
            continue
        try:
            html = fetch_text(url, timeout=15.0)
            quote = parse_shop_html(url, html)
            if quote:
                d["price_eur"] = quote.price_eur
                d["shop"]["price_eur"] = quote.price_eur
                d["shop"]["in_stock"] = quote.in_stock
                d["shop"]["checked"] = quote.checked[:7]
                updated += 1
            else:
                failed += 1
        except Exception:
            failed += 1
        time.sleep(delay)
    if not dry_run and updated:
        DRIVERS_PATH.write_text(json.dumps(data, indent=2) + "\n")
    return updated, failed


def main() -> int:
    ap = argparse.ArgumentParser(description="Sync unified driver catalog (app/data/drivers.json) and optional live EU prices.")
    ap.add_argument("--prices", action="store_true", help="Also refresh live EUR prices & stock for curated drivers")
    ap.add_argument("--delay", type=float, default=2.0, help="Seconds between shop requests when --prices is used (default: 2.0)")
    ap.add_argument("--dry-run", action="store_true", help="Fetch and parse without writing files")
    args = ap.parse_args()

    total, eu = sync_catalog(dry_run=args.dry_run)
    print(f"drivers.json: {total} drivers ({eu} with SoundImports EU links){' [dry-run]' if args.dry_run else ''}")
    if args.prices:
        up, fail = sync_curated_prices(delay=args.delay, dry_run=args.dry_run)
        print(f"curated prices: {up} updated, {fail} failed{' [dry-run]' if args.dry_run else ''}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
