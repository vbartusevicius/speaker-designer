"""FastAPI entrypoint using Pydantic request schemas, DriverRepository, SpeakerSystem, and ExportSpec registries."""
from __future__ import annotations

import os
import time
from pathlib import Path
from typing import Any

import plotly
from fastapi import Body, FastAPI, HTTPException, Request
from fastapi.responses import FileResponse, JSONResponse, Response
from fastapi.staticfiles import StaticFiles

from .design import catalog, drivers_db, export
from .design import measurements as meas
from .design.cabinet import DEFAULT_FIT, geometry
from .design.layout import check_layout
from .design.optimizer import optimise
from .design.ports import port_options
from .design.potential import potential
from .design.system import DEFAULT_DESIGN, bem_request, simulate_design
from .design.systems import get_system
from .design.tuner import maximize, tune
from .schemas import (
    DriverImportRequest,
    FetchPricesRequest,
    LayoutCheckRequest,
    MeasurementUploadRequest,
    OptimizeRequest,
    ReverseRequest,
    SubReverseRequest,
)

STATIC = Path(__file__).parent / "static"
PLOTLY_JS = Path(plotly.__file__).parent / "package_data" / "plotly.min.js"
READ_ONLY = os.environ.get("READ_ONLY", "0") == "1"

app = FastAPI(title="Speaker Designer", version="1.0.0")
app.mount("/static", StaticFiles(directory=STATIC), name="static")


@app.exception_handler(ValueError)
@app.exception_handler(KeyError)
async def _bad_request(_: Request, exc: Exception) -> JSONResponse:
    return JSONResponse(status_code=400, content={"detail": str(exc).strip("'\"")})


@app.middleware("http")
async def read_only_guard(request: Request, call_next):
    if READ_ONLY and request.url.path.startswith(("/api/drivers", "/api/driver-base")) and request.method in ("POST", "DELETE"):
        return JSONResponse(
            {"detail": "This public instance is read-only: run your own copy (docker compose up) to add drivers, fetch prices, or upload measurements."},
            status_code=403,
        )
    return await call_next(request)


@app.get("/", include_in_schema=False)
def index() -> FileResponse:
    return FileResponse(STATIC / "index.html")


@app.get("/vendor/plotly.min.js", include_in_schema=False)
def plotly_js() -> FileResponse:
    return FileResponse(PLOTLY_JS, media_type="application/javascript")


@app.get("/api/health")
def health() -> dict[str, bool]:
    return {"ok": True}


@app.get("/api/config")
def config() -> dict[str, bool]:
    return {"read_only": READ_ONLY}


@app.get("/api/defaults")
def defaults() -> dict[str, Any]:
    return {"design": DEFAULT_DESIGN, "cabinet": DEFAULT_FIT}


@app.get("/api/drivers")
def list_drivers() -> list[dict[str, Any]]:
    flags = drivers_db.measured_flags()
    return [{**d.to_dict(), "measured": flags.get(d.id, [])} for d in drivers_db.all_drivers().values()]


@app.post("/api/drivers")
def add_driver(d: dict[str, Any] = Body(...)) -> dict[str, Any]:
    try:
        return drivers_db.save_custom(d).to_dict()
    except (TypeError, ValueError, ZeroDivisionError) as e:
        raise HTTPException(400, f"invalid driver: {e}")


@app.delete("/api/drivers/{driver_id}")
def delete_driver(driver_id: str) -> dict[str, str]:
    if not drivers_db.delete_custom(driver_id):
        raise HTTPException(404, "custom driver not found (built-in drivers cannot be deleted)")
    return {"deleted": driver_id}


@app.get("/api/drivers/{driver_id}/measurements")
def get_measurements(driver_id: str) -> dict[str, Any]:
    return meas.summary(driver_id)


@app.post("/api/drivers/{driver_id}/measurements/{kind}")
def put_measurement(driver_id: str, kind: str, body: MeasurementUploadRequest) -> dict[str, Any]:
    drivers_db.get(driver_id)
    return meas.save(driver_id, kind, body.text, {"source": body.source, "filename": body.filename})


@app.delete("/api/drivers/{driver_id}/measurements/{kind}")
def del_measurement(driver_id: str, kind: str) -> dict[str, bool]:
    return {"deleted": meas.delete(driver_id, kind)}


@app.get("/api/driver-base/search")
def driver_catalog_search(q: str = "", role: str = "", eu_only: bool = False, limit: int = 30) -> list[dict[str, Any]]:
    all_dicts = [d.to_dict() for d in drivers_db.all_drivers().values()]
    return catalog.search_catalog(all_dicts, q, role or None, eu_only, min(limit, 60))


@app.post("/api/driver-base/import")
def driver_catalog_import(body: DriverImportRequest) -> dict[str, Any]:
    return drivers_db.import_from_driver_base(body.id, body.fetch_price).to_dict()


@app.get("/api/drivers/{driver_id}/replacements")
def driver_replacements(driver_id: str, limit: int = 10) -> dict[str, Any]:
    drv = drivers_db.get(driver_id)
    assert drv is not None
    target = drv.to_dict()
    all_dicts = [d.to_dict() for d in drivers_db.all_drivers().values()]
    return {"target": target, "replacements": catalog.find_replacements(target, all_dicts, min(limit, 20))}


@app.get("/api/catalog/price")
def catalog_price(url: str, force: bool = False) -> dict[str, Any]:
    return catalog.fetch_live_price(url, force=force)


@app.post("/api/drivers/fetch-prices")
def fetch_all_prices(body: FetchPricesRequest = Body(default_factory=FetchPricesRequest)) -> dict[str, list[dict[str, Any]]]:
    ids = set(body.ids)
    updated: list[dict[str, Any]] = []
    failed: list[dict[str, Any]] = []
    for drv in drivers_db.all_drivers().values():
        if ids:
            if drv.id not in ids:
                continue
        elif drv.price_eur <= 0:
            continue
        url = (drv.shop or {}).get("url")
        if not url:
            continue
        try:
            res = catalog.fetch_live_price(url, force=body.force)
            updated.append({"id": drv.id, **res})
            if not res.get("cached"):
                time.sleep(0.35)
        except Exception as e:
            failed.append({"id": drv.id, "error": str(e)})
    return {"updated": updated, "failed": failed}


@app.post("/api/bem/start")
def bem_start(design: dict[str, Any] = Body(...)) -> dict[str, Any]:
    from .design import bem
    if any(j["status"] == "running" for j in bem.JOBS.values()):
        raise HTTPException(429, "A BEM calculation is already running on this server - try again in a few minutes.")
    req = bem_request(design)
    job = bem.start(req)
    return {"id": job["id"], "positions_key": req["positions_key"], "frequencies": req["freqs"]}


@app.get("/api/bem/{jid}")
def bem_status(jid: str) -> dict[str, Any]:
    from .design import bem
    try:
        return bem.status(jid)
    except KeyError as e:
        raise HTTPException(404, str(e))


@app.post("/api/spice")
def spice_check(design: dict[str, Any] = Body(...)) -> dict[str, Any]:
    from .design.spice import run
    r = simulate_design(design)
    d = r["design"]["drivers"]
    drv = {
        "woofer": drivers_db.get(d["woofer"]["id"]),
        "mid": drivers_db.get((d.get("mid") or {}).get("id")),
        "tweeter": drivers_db.get(d["tweeter"]["id"]),
    }
    return run(r, drv)


@app.post("/api/port/options")
def port_opts(design: dict[str, Any] = Body(...)) -> list[dict[str, Any]]:
    return port_options(design)


@app.post("/api/cabinet")
def cabinet(c: dict[str, Any] = Body(...)) -> dict[str, Any]:
    return geometry(c).to_dict()


@app.post("/api/simulate")
def simulate(design: dict[str, Any] = Body(...)) -> dict[str, Any]:
    return get_system(design).simulate(design)


@app.post("/api/optimize")
def optimize(req: OptimizeRequest) -> dict[str, Any]:
    return optimise(req.model_dump())


@app.post("/api/potential")
def cabinet_potential(c: dict[str, Any] = Body(...)) -> dict[str, Any]:
    return potential(c.get("cabinet", c), bool(c.get("three_way", True)))


@app.post("/api/tune")
def tune_design(design: dict[str, Any] = Body(...)) -> dict[str, Any]:
    return tune(design)


@app.post("/api/maximize")
def maximize_design(design: dict[str, Any] = Body(...)) -> dict[str, Any]:
    return maximize(design)


@app.post("/api/layout/check")
def layout_check(body: LayoutCheckRequest) -> dict[str, Any]:
    return check_layout(body.design, body.port)


@app.post("/api/reverse")
def reverse_design(req: ReverseRequest) -> dict[str, Any]:
    return get_system("full_range").reverse(req.model_dump())


@app.post("/api/sub/simulate")
def sub_simulate(design: dict[str, Any] = Body(...)) -> dict[str, Any]:
    return get_system("sub").simulate(design)


@app.post("/api/sub/reverse")
def sub_reverse(req: SubReverseRequest) -> dict[str, Any]:
    return get_system("sub").reverse(req.model_dump())


def _parts(design: dict[str, Any]) -> tuple[dict[str, Any], list[dict[str, Any]]]:
    r = get_system(design).simulate(design)
    d = r["design"]["drivers"]
    drv = {
        "woofer": drivers_db.get(d["woofer"]["id"]),
        "mid": drivers_db.get((d.get("mid") or {}).get("id")),
        "tweeter": drivers_db.get((d.get("tweeter") or {}).get("id")),
    }
    return r, export.build_parts(r, drv)


@app.post("/api/export/parts")
def export_parts(design: dict[str, Any] = Body(...)) -> list[dict[str, Any]]:
    _, parts = _parts(design)
    return parts


@app.post("/api/export/{fmt}")
def export_file(fmt: str, design: dict[str, Any] = Body(...), part: str | None = None) -> Response:
    spec = export.EXPORTERS.get(fmt)
    if not spec:
        raise HTTPException(404, "unknown format")
    r, parts = _parts(design)
    if part:
        parts = [p for p in parts if p["name"] == part]
        if not parts:
            raise HTTPException(404, "unknown part")
    payload = spec.render(r, parts)
    return Response(payload, media_type=spec.media_type, headers={"Content-Disposition": f'attachment; filename="{spec.filename}"'})
