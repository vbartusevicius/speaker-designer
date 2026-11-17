"""EU catalog price providers (Strategy pattern), thread-safe PriceCache, SKU search,
and acoustic + mechanical drop-in replacement finder.
"""
from __future__ import annotations

import json
import math
import os
import re
import threading
import time
import urllib.request
from pathlib import Path
from typing import Any, Iterable, Optional, Protocol

from .models import PriceQuote, ReplacementCandidate

CACHE_TTL_S = 3600.0


def cache_path() -> Path:
    default = Path(__file__).resolve().parents[2] / "userdata" / "price_cache.json"
    return Path(os.environ.get("PRICE_CACHE_PATH", default))


class ShopPriceProvider(Protocol):
    """Extension point for parsing EUR price & stock from an EU shop HTML page."""

    name: str

    def matches(self, url: str) -> bool: ...
    def parse(self, url: str, html: str) -> Optional[PriceQuote]: ...


class JsonLdProductProvider:
    """Generic Schema.org JSON-LD @type=Product parser (used by SoundImports and modern EU shops)."""

    name = "Schema.org JSON-LD"

    def matches(self, url: str) -> bool:
        return True

    def parse(self, url: str, html: str) -> Optional[PriceQuote]:
        blocks = re.findall(r'<script[^>]*type=["\']application/ld\+json["\'][^>]*>(.*?)</script>', html, re.S | re.I)
        for block in blocks:
            try:
                obj = json.loads(block.strip(), strict=False)
            except Exception:
                continue
            items = obj if isinstance(obj, list) else [obj]
            for it in items:
                if not isinstance(it, dict):
                    continue
                types = it.get("@type")
                is_product = types == "Product" or (isinstance(types, list) and "Product" in types)
                if not is_product:
                    continue
                offers = it.get("offers")
                if isinstance(offers, list):
                    offers = offers[0] if offers else {}
                if not isinstance(offers, dict) or offers.get("price") is None:
                    continue
                try:
                    price = float(str(offers["price"]).replace(",", "."))
                except ValueError:
                    continue
                avail = str(offers.get("availability", ""))
                return PriceQuote(
                    price_eur=round(price, 2),
                    currency=str(offers.get("priceCurrency", "EUR")),
                    in_stock=("InStock" in avail or "PreOrder" in avail),
                    sku=it.get("sku"),
                    url=url,
                    checked=time.strftime("%Y-%m-%d"),
                    ts=time.time(),
                )
        return None


class AudiophonicsMicrodataProvider:
    """Microdata fallback for Audiophonics (FR) product pages."""

    name = "Audiophonics Microdata"

    def matches(self, url: str) -> bool:
        return "audiophonics.fr" in url.lower()

    def parse(self, url: str, html: str) -> Optional[PriceQuote]:
        m_cur = re.search(r'itemprop=["\']priceCurrency["\'][^>]*content=["\']([A-Z]{3})["\']', html, re.I)
        m_price = re.search(r'id=["\']our_price_display["\'][^>]*content=["\']([\d.,]+)["\']', html, re.I) or \
                  re.search(r'itemprop=["\']price["\'][^>]*content=["\']([\d.,]+)["\']', html, re.I)
        if not m_price:
            return None
        try:
            price = float(m_price.group(1).replace(",", "."))
        except ValueError:
            return None
        avail_m = re.search(r'itemprop=["\']availability["\'][^>]*href=["\']([^"\']+)["\']', html, re.I)
        in_stock = True if not avail_m else ("InStock" in avail_m.group(1))
        return PriceQuote(
            price_eur=round(price, 2),
            currency=m_cur.group(1) if m_cur else "EUR",
            in_stock=in_stock,
            sku=None,
            url=url,
            checked=time.strftime("%Y-%m-%d"),
            ts=time.time(),
        )


SHOP_PROVIDERS: list[ShopPriceProvider] = [
    JsonLdProductProvider(),
    AudiophonicsMicrodataProvider(),
]


def register_price_provider(provider: ShopPriceProvider) -> None:
    """Register an additional EU shop price parser at the front of the chain."""
    SHOP_PROVIDERS.insert(0, provider)


def parse_shop_html(url: str, html: str) -> Optional[dict[str, Any]]:
    for provider in SHOP_PROVIDERS:
        if provider.matches(url):
            quote = provider.parse(url, html)
            if quote is not None:
                return quote.to_dict()
    return None


class PriceCache:
    """Thread-safe, mtime-cached JSON store for live EU price quotes."""

    def __init__(self, path_fn=cache_path) -> None:
        self._path_fn = path_fn
        self._lock = threading.Lock()
        self._mem: Optional[tuple[str, int, dict[str, dict[str, Any]]]] = None

    def path(self) -> Path:
        return self._path_fn()

    def load(self) -> dict[str, dict[str, Any]]:
        p = self.path()
        if not p.exists():
            return {}
        mt = p.stat().st_mtime_ns
        if self._mem and self._mem[0] == str(p) and self._mem[1] == mt:
            return self._mem[2]
        try:
            data = json.loads(p.read_text())
            self._mem = (str(p), mt, data)
            return data
        except Exception:
            return {}

    def get(self, url: Optional[str]) -> Optional[dict[str, Any]]:
        return self.load().get(url) if url else None

    def put(self, url: str, quote: dict[str, Any]) -> None:
        with self._lock:
            cache = dict(self.load())
            cache[url] = quote
            p = self.path()
            p.parent.mkdir(parents=True, exist_ok=True)
            p.write_text(json.dumps(cache, indent=1))
            self._mem = (str(p), p.stat().st_mtime_ns, cache)

    def signature(self) -> tuple[str, int]:
        p = self.path()
        return (str(p), p.stat().st_mtime_ns if p.exists() else 0)


PRICE_CACHE = PriceCache()


def cached_price(url: Optional[str]) -> Optional[dict[str, Any]]:
    return PRICE_CACHE.get(url)


def fetch_live_price(url: str, force: bool = False, timeout: float = 10.0) -> dict[str, Any]:
    if not url or not url.startswith(("https://", "http://")):
        raise ValueError("missing or invalid shop URL")
    hit = PRICE_CACHE.get(url)
    if not force and hit and (time.time() - hit.get("ts", 0) < CACHE_TTL_S):
        return {**hit, "cached": True}

    req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0 (compatible; SpeakerDesigner/1.0)"})
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        html = resp.read().decode("utf-8", "ignore")
    parsed = parse_shop_html(url, html)
    if not parsed:
        raise ValueError("could not extract price/stock from shop page")
    PRICE_CACHE.put(url, parsed)
    return {**parsed, "cached": False}


def search_catalog(drivers: Iterable[dict[str, Any]], q: str, role: Optional[str] = None,
                   eu_only: bool = False, limit: int = 30) -> list[dict[str, Any]]:
    tokens = [t for t in re.split(r"[\s,/]+", (q or "").strip().lower()) if t]
    scored: list[tuple[int, str, str, dict[str, Any]]] = []
    q_low = (q or "").strip().lower()
    joined = "".join(tokens)

    for d in drivers:
        if role and d.get("role") != role:
            continue
        shop_url = (d.get("shop") or {}).get("url")
        if eu_only and not shop_url:
            continue
        nom = float(d.get("nominal_mm") or 0)
        hay = f"{d.get('brand', '')} {d.get('model', '')} {d.get('id', '')} {d.get('role', '')} {int(round(nom))}mm {int(round(nom / 10))}cm".lower()
        if tokens and not all(t in hay for t in tokens):
            continue

        score = 0
        ml = str(d.get("model", "")).lower()
        if tokens:
            if ml == joined or ml == q_low:
                score += 100
            elif ml.startswith(tokens[0]):
                score += 40
        if shop_url:
            score += 20
        if d.get("dims_verified"):
            score += 5
        scored.append((score, str(d.get("brand", "")), str(d.get("model", "")), d))

    scored.sort(key=lambda x: (-x[0], x[1], x[2]))
    return [x[3] for x in scored[:limit]]


def _norm_key(d: dict[str, Any]) -> str:
    return re.sub(r"[^a-z0-9]+", "", f"{d.get('brand', '')}{d.get('model', '')}".lower())


def _compatible_roles(role: str) -> set[str]:
    groups = {
        "woofer": {"woofer", "subwoofer", "midwoofer"},
        "subwoofer": {"woofer", "subwoofer", "midwoofer"},
        "midwoofer": {"midwoofer", "woofer", "mid"},
        "mid": {"mid", "midwoofer"},
    }
    return groups.get(role, {role})


def find_replacements(target: dict[str, Any], catalog: Iterable[dict[str, Any]], limit: int = 10) -> list[dict[str, Any]]:
    """Rank drop-in acoustic + mechanical replacements across the unified driver catalog."""
    t_role = str(target.get("role", "woofer"))
    allowed = _compatible_roles(t_role)
    t_key = _norm_key(target)
    t_cut = float(target.get("cutout_d_mm") or 150)
    t_out = float(target.get("outer_d_mm") or 175)
    t_dep = float(target.get("depth_mm") or 75)
    t_fs = float(target.get("Fs") or 50)
    t_qts = float(target.get("Qts") or 0.4)
    t_vas = float(target.get("Vas_L") or 0)
    t_sens = float(target.get("sens_db") or 88)
    t_z = float(target.get("Z_nom") or 8)
    t_re = float(target.get("Re") or 6)
    t_sd = float(target.get("Sd_cm2") or 100)

    seen_keys = {t_key}
    candidates: list[ReplacementCandidate] = []

    for d in catalog:
        nk = _norm_key(d)
        if not nk or nk in seen_keys or d.get("role") not in allowed:
            continue
        seen_keys.add(nk)

        cut = float(d.get("cutout_d_mm") or t_cut)
        out = float(d.get("outer_d_mm") or t_out)
        dep = float(d.get("depth_mm") or t_dep)
        sd = float(d.get("Sd_cm2") or t_sd)
        verified_dims = bool(d.get("dims_verified"))
        if verified_dims and (abs(cut - t_cut) > 25 or abs(out - t_out) > 35):
            continue
        if not verified_dims and t_role != "tweeter" and abs(math.log(max(sd, 1) / max(t_sd, 1))) > 0.35:
            continue

        pen = 0.0
        notes: list[str] = []

        if verified_dims:
            dc = cut - t_cut
            if abs(dc) <= 2:
                notes.append("same cut-out")
            else:
                notes.append(f"cut-out {dc:+.0f} mm")
                pen += abs(dc) * (1.1 if dc > 0 else 0.7)
            pen += abs(out - t_out) * 0.35
            if dep > t_dep + 8:
                pen += (dep - t_dep - 8) * 0.6
                notes.append(f"deeper +{dep - t_dep:.0f} mm")
        elif t_role != "tweeter":
            pen += 12.0 * abs(math.log(max(sd, 1) / max(t_sd, 1)))
            notes.append(f"cone {sd:.0f} vs {t_sd:.0f} cm² (dims est.)")

        if t_role != "tweeter":
            fs = float(d.get("Fs") or t_fs)
            qts = float(d.get("Qts") or t_qts)
            vas = float(d.get("Vas_L") or t_vas or 1.0)
            pen += 22.0 * abs(math.log(max(fs, 10) / max(t_fs, 10))) + 26.0 * abs(qts - t_qts)
            if t_vas > 0 and vas > 0:
                pen += 14.0 * abs(math.log(vas / t_vas))
            notes.append(f"Fs {fs:.0f} vs {t_fs:.0f} Hz · Qts {qts:.2f}")

        sens = float(d.get("sens_db") or t_sens)
        z = float(d.get("Z_nom") or t_z)
        re_ = float(d.get("Re") or t_re)
        ds = sens - t_sens
        pen += abs(ds) * 2.2
        if abs(ds) >= 0.8:
            notes.append(f"sens {ds:+.1f} dB")
        if abs(z - t_z) > 1.5 or abs(re_ - t_re) > 1.5:
            pen += 10.0
            notes.append(f"{z:.0f} Ω vs {t_z:.0f} Ω")
        else:
            notes.append(f"same {z:.0f} Ω")

        if d.get("role") != t_role:
            pen += 4.0

        shop = d.get("shop") or {}
        shop_url = shop.get("url")
        if shop_url:
            pen -= 4.0

        match_pct = max(5, min(99, round(100 - pen * 1.45)))
        price = d.get("price_eur") or shop.get("price_eur")
        candidates.append(ReplacementCandidate(
            driver=d,
            id=str(d["id"]),
            brand=str(d["brand"]),
            model=str(d["model"]),
            role=str(d["role"]),
            nominal_mm=float(d["nominal_mm"]),
            match_pct=match_pct,
            notes=notes,
            shop_url=shop_url,
            price_eur=float(price) if price else None,
            in_stock=shop.get("in_stock") if shop else None,
        ))

    candidates.sort(key=lambda c: (-c.match_pct, 0 if c.shop_url else 1))
    return [c.to_dict() for c in candidates[:limit]]
