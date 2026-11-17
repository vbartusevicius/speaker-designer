"""DriverRepository: unified access to built-in (drivers.json), custom drivers, and live price overrides."""
from __future__ import annotations

import json
import os
import threading
from pathlib import Path
from typing import Any, Callable, Optional

from ..physics.driver import Driver
from . import catalog

BUILTIN_PATH = Path(__file__).resolve().parent.parent / "data" / "drivers.json"


def custom_path() -> Path:
    default = Path(__file__).resolve().parents[2] / "userdata" / "custom_drivers.json"
    return Path(os.environ.get("CUSTOM_DRIVERS_PATH", default))


class DriverRepository:
    """Thread-safe, mtime-cached repository over unified built-in + custom drivers + live price cache."""

    def __init__(self, builtin_path: Path = BUILTIN_PATH, custom_path_fn: Callable[[], Path] = custom_path,
                 price_cache: catalog.PriceCache = catalog.PRICE_CACHE) -> None:
        self._builtin_path = builtin_path
        self._custom_path_fn = custom_path_fn
        self._price_cache = price_cache
        self._lock = threading.Lock()
        self._builtin_raw: Optional[list[dict[str, Any]]] = None
        self._cache_key: Optional[tuple[Any, ...]] = None
        self._drivers_cache: dict[str, Driver] = {}

    def _load_builtin(self) -> list[dict[str, Any]]:
        if self._builtin_raw is None:
            self._builtin_raw = json.loads(self._builtin_path.read_text()).get("drivers", [])
        return self._builtin_raw

    def _load_custom(self) -> list[dict[str, Any]]:
        p = self._custom_path_fn()
        if not p.exists():
            return []
        return json.loads(p.read_text()).get("drivers", [])

    def _overlay_price(self, d: dict[str, Any], prices: dict[str, dict[str, Any]]) -> dict[str, Any]:
        shop = dict(d.get("shop") or {})
        url = shop.get("url")
        quote = prices.get(url) if url else None
        if not quote:
            return d
        out = dict(d)
        out["price_eur"] = quote["price_eur"]
        out["shop"] = {
            **shop,
            "url": url,
            "price_eur": quote["price_eur"],
            "in_stock": quote["in_stock"],
            "checked": quote["checked"],
        }
        return out

    def all(self) -> dict[str, Driver]:
        cp = self._custom_path_fn()
        key = (
            str(cp),
            cp.stat().st_mtime_ns if cp.exists() else 0,
            *self._price_cache.signature(),
        )
        if self._cache_key == key and self._drivers_cache:
            return self._drivers_cache

        prices = self._price_cache.load()
        out = {d["id"]: Driver.from_dict(self._overlay_price(d, prices)) for d in self._load_builtin()}
        for d in self._load_custom():
            out[d["id"]] = Driver.from_dict(self._overlay_price({**d, "custom": True}, prices))

        self._cache_key = key
        self._drivers_cache = out
        return out

    def get(self, driver_id: Optional[str]) -> Optional[Driver]:
        if not driver_id:
            return None
        drv = self.all().get(driver_id)
        if drv is None:
            raise KeyError(f"unknown driver '{driver_id}'")
        return drv

    def require(self, driver_id: str) -> Driver:
        drv = self.all().get(driver_id)
        if drv is None:
            raise KeyError(f"unknown driver '{driver_id}'")
        return drv

    def save_custom(self, d: dict[str, Any]) -> Driver:
        drv = Driver.from_dict({**d, "custom": True})
        _ = drv.Qts, drv.Bl  # validate numerics
        with self._lock:
            items = [x for x in self._load_custom() if x["id"] != drv.id]
            items.append({k: v for k, v in drv.__dict__.items()})
            p = self._custom_path_fn()
            p.parent.mkdir(parents=True, exist_ok=True)
            p.write_text(json.dumps({"drivers": items}, indent=2))
            self._cache_key = None
        return drv

    def delete_custom(self, driver_id: str) -> bool:
        with self._lock:
            items = self._load_custom()
            keep = [x for x in items if x["id"] != driver_id]
            if len(keep) == len(items):
                return False
            self._custom_path_fn().write_text(json.dumps({"drivers": keep}, indent=2))
            self._cache_key = None
        return True

    def ensure_priced(self, driver_id: str, fetch_price: bool = True) -> Driver:
        drv = self.require(driver_id)
        url = (drv.shop or {}).get("url")
        if fetch_price and url and drv.price_eur <= 0:
            try:
                catalog.fetch_live_price(url)
                self._cache_key = None
                drv = self.require(driver_id)
            except Exception:
                pass
        return drv


REPO = DriverRepository()


def all_drivers() -> dict[str, Driver]:
    return REPO.all()


def get(driver_id: Optional[str]) -> Optional[Driver]:
    return REPO.get(driver_id)


def require(driver_id: str) -> Driver:
    return REPO.require(driver_id)


def save_custom(d: dict[str, Any]) -> Driver:
    return REPO.save_custom(d)


def delete_custom(driver_id: str) -> bool:
    return REPO.delete_custom(driver_id)


def import_from_driver_base(db_id: str, fetch_price: bool = False) -> Driver:
    return REPO.ensure_priced(db_id, fetch_price=fetch_price)


def measured_flags() -> dict[str, list[str]]:
    from . import measurements as meas
    root = meas.root()
    if not root.exists():
        return {}
    return {d.name: sorted(p.stem for p in d.glob("*.json")) for d in root.iterdir() if d.is_dir()}
