"""Embedded BEM verification (bempp-cl, MIT): exterior radiation of a rectangular cabinet with pistons
on the front face.  Burton-Miller direct formulation (no fictitious interior resonances).
Results are transfer functions relative to the same piston radiating into half space (infinite wall),
i.e. directly comparable with the fast edge-diffraction model of the main app.

Conventions: time e^{-iwt}, G = e^{ikr}/(4 pi r), normal n points out of the cabinet into the air.
Exterior representation: p = D[p] - S[dp/dn];  boundary: (1/2 I - K + eta W) p = (-V - eta(1/2 I + K')) g,
g = dp/dn = i w rho v_n,  eta = i/k.
"""
from __future__ import annotations

import math
import threading
import time
import uuid

import bempp.api
import numpy as np
from bempp.api.operators.boundary import helmholtz, sparse
from bempp.api.operators.potential import helmholtz as hpot

bempp.api.DEFAULT_DEVICE_INTERFACE = "numba"
RHO, C = 1.204, 343.0
JOBS: dict = {}


def dense(op):
    return np.asarray(op.weak_form().to_dense())


def box_grid(W, H, D, h):
    """Watertight triangulated box x[0,W] y[0,H] z[-D,0]; front face at z=0. Triangles oriented outward."""
    faces = [  # origin, u, v  (u x v = outward normal)
        ((0, 0, 0), (W, 0, 0), (0, H, 0)),        # front  +z
        ((W, 0, -D), (-W, 0, 0), (0, H, 0)),      # back   -z
        ((0, 0, -D), (0, 0, D), (0, H, 0)),       # left   -x
        ((W, 0, 0), (0, 0, -D), (0, H, 0)),       # right  +x
        ((0, 0, -D), (W, 0, 0), (0, 0, D)),       # bottom -y
        ((0, H, 0), (W, 0, 0), (0, 0, -D)),       # top    +y
    ]
    verts: list[tuple[float, ...]] = []
    index: dict[tuple[float, ...], int] = {}
    tris: list[tuple[int, int, int]] = []
    front: list[bool] = []

    def vid(p):
        key = tuple(round(c, 6) for c in p)
        if key not in index:
            index[key] = len(verts)
            verts.append(key)
        return index[key]

    for fi, (o0, u0, v0) in enumerate(faces):
        o, u, v = np.array(o0, dtype=float), np.array(u0, dtype=float), np.array(v0, dtype=float)
        nu, nv = max(1, int(math.ceil(np.linalg.norm(u) / h))), max(1, int(math.ceil(np.linalg.norm(v) / h)))
        for i in range(nu):
            for j in range(nv):
                a = vid(o + u * i / nu + v * j / nv)
                b = vid(o + u * (i + 1) / nu + v * j / nv)
                c = vid(o + u * (i + 1) / nu + v * (j + 1) / nv)
                dd = vid(o + u * i / nu + v * (j + 1) / nv)
                tris += [(a, b, c), (a, c, dd)]
                front += [fi == 0, fi == 0]
    return bempp.api.Grid(np.array(verts).T, np.array(tris).T), np.array(front)


def piston_velocity(grid, front, x, y, r):
    """Unit volume velocity spread over front-face elements inside the piston (at least the nearest one)."""
    cen = grid.centroids
    areas = grid.volumes
    d = np.hypot(cen[:, 0] - x, cen[:, 1] - y)
    inside = front & (d <= r)
    if not inside.any():
        inside = np.zeros_like(front)
        inside[np.argmin(np.where(front, d, np.inf))] = True
    v = np.where(inside, 1.0, 0.0)
    return v / float((v * areas).sum())  # normal velocity giving U = 1 m^3/s


def solve(req: dict, progress=None):
    W, H, D = req["box"]["w"], req["box"]["h"], req["box"]["d"]
    pistons, freqs = req["pistons"], req["freqs"]
    lx, ly, R = req["listener"]["x"], req["listener"]["y"], req["listener"]["dist"]
    angles = req.get("angles", [0, 15, 30, 45, 60, 75, 90])
    pts = np.array([[lx + R * math.sin(math.radians(a)), ly, R * math.cos(math.radians(a))] for a in angles]).T
    from typing import Any
    out: dict[str, dict[str, Any]] = {p["name"]: {"re": [], "im": [], "polar_db": {str(a): [] for a in angles}} for p in pistons}
    grids = {}
    t0 = time.time()
    for n, f in enumerate(freqs):
        k = 2 * math.pi * f / C
        h = min(0.05, C / f / 6.0)
        h = round(h, 3)
        if h not in grids:
            grids[h] = box_grid(W, H, D, h)
        grid, front = grids[h]
        p1 = bempp.api.function_space(grid, "P", 1)
        dp0 = bempp.api.function_space(grid, "DP", 0)
        eta = 1j / k
        lhs = (0.5 * sparse.identity(p1, p1, p1) - helmholtz.double_layer(p1, p1, p1, k)
               + eta * helmholtz.hypersingular(p1, p1, p1, k))
        rhs_op = (-1 * helmholtz.single_layer(dp0, p1, p1, k)
                  - eta * (0.5 * sparse.identity(dp0, p1, p1) + helmholtz.adjoint_double_layer(dp0, p1, p1, k)))
        A = dense(lhs)
        B = dense(rhs_op)
        lu = __import__("scipy.linalg", fromlist=["lu_factor"])
        fac = lu.lu_factor(A)
        dlp_pot = hpot.double_layer(p1, pts, k)
        slp_pot = hpot.single_layer(dp0, pts, k)
        for pc in pistons:
            vn = piston_velocity(grid, front, pc["x"], pc["y"], pc["r"])
            g = 1j * 2 * math.pi * f * RHO * vn
            gfun = bempp.api.GridFunction(dp0, coefficients=g)
            pc_ = lu.lu_solve(fac, B @ g)
            pfun = bempp.api.GridFunction(p1, coefficients=pc_)
            pf = (dlp_pot.evaluate(pfun) - slp_pot.evaluate(gfun)).ravel()
            # reference: same unit volume velocity into half space, on axis, same distance
            r0 = np.linalg.norm(np.array([pc["x"], pc["y"], 0.0]) - pts[:, 0])
            ref = -1j * 2 * math.pi * f * RHO / (2 * math.pi) * np.exp(1j * k * r0) / r0
            tr = pf[0] / ref
            out[pc["name"]]["re"].append(float(tr.real))
            out[pc["name"]]["im"].append(float(tr.imag))
            for i, a in enumerate(angles):
                out[pc["name"]]["polar_db"][str(a)].append(float(20 * math.log10(abs(pf[i] / ref) + 1e-12)))
        if progress:
            progress(n + 1, len(freqs), time.time() - t0, grid.number_of_elements)
    return {"freqs": freqs, "angles": angles, "pistons": out, "elements_max": max(g[0].number_of_elements for g in grids.values()),
            "seconds": round(time.time() - t0, 1)}


def health():
    return {"ok": True, "bempp": bempp.api.__version__ if hasattr(bempp.api, "__version__") else "bempp-cl"}


def start(req: dict):
    jid = uuid.uuid4().hex[:10]
    JOBS[jid] = {"status": "running", "done": 0, "total": len(req["freqs"])}

    def work():
        try:
            def prog(n, tot, sec, el):
                JOBS[jid].update(done=n, total=tot, seconds=round(sec, 1), elements=el)
            JOBS[jid].update(status="done", result=solve(req, prog))
        except Exception as e:  # report to the caller
            JOBS[jid].update(status="error", error=str(e))
    threading.Thread(target=work, daemon=True).start()
    return {"id": jid}


def status(jid: str):
    if jid not in JOBS:
        raise KeyError("unknown BEM job")
    return JOBS[jid]


def selftest():
    """Pulsating sphere check of the formulation: p(r) = rho c v (ka/(ka+i))... evaluated numerically."""
    grid = bempp.api.shapes.regular_sphere(3)
    a, f = 1.0, 100.0
    k = 2 * math.pi * f / C
    p1 = bempp.api.function_space(grid, "P", 1)
    dp0 = bempp.api.function_space(grid, "DP", 0)
    eta = 1j / k
    lhs = 0.5 * sparse.identity(p1, p1, p1) - helmholtz.double_layer(p1, p1, p1, k) + eta * helmholtz.hypersingular(p1, p1, p1, k)
    rhs = -1 * helmholtz.single_layer(dp0, p1, p1, k) - eta * (0.5 * sparse.identity(dp0, p1, p1) + helmholtz.adjoint_double_layer(dp0, p1, p1, k))
    g = np.full(grid.number_of_elements, 1j * 2 * math.pi * f * RHO * 1.0)
    pc = np.linalg.solve(dense(lhs), dense(rhs) @ g)
    pt = np.array([[5.0], [0.0], [0.0]])
    p = (hpot.double_layer(p1, pt, k).evaluate(bempp.api.GridFunction(p1, coefficients=pc))
         - hpot.single_layer(dp0, pt, k).evaluate(bempp.api.GridFunction(dp0, coefficients=g))).ravel()[0]
    # analytic pulsating sphere, e^{-iwt}: p = rho c v a/r * (-ika)/(1 - ika) e^{ik(r-a)}
    r = 5.0
    exact = RHO * C * 1.0 * a / r * (-1j * k * a) / (1 - 1j * k * a) * np.exp(1j * k * (r - a))
    return {"bem": [p.real, p.imag], "exact": [exact.real, exact.imag], "rel_error": float(abs(p - exact) / abs(exact))}
