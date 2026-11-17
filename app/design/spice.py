"""ngspice (BSD) cross-check of the passive crossover: the same ladder networks are written as a SPICE
netlist with an electrical equivalent circuit for every driver (Re, Le, Res||Lces||Cmes, sealed-box
compliance as Lceb), solved with an AC sweep, and compared with the internal network solver."""
from __future__ import annotations

import math
import os
import subprocess
import tempfile

import numpy as np

from ..physics import crossover as xo
from ..physics.constants import C, RHO


def equivalent(drv, box_L: float | None):
    """Electrical equivalent of the driver (+ sealed box) for SPICE and for the matching Python impedance."""
    bl2 = drv.Bl ** 2
    e = {"Re": drv.Re, "Le": drv.Le_mH * 1e-3, "Res": bl2 / drv.Rms, "Cmes": drv.Mms / bl2}
    if drv.Cms:
        lces = drv.Cms * bl2
        if box_L:
            lceb = box_L * 1e-3 / (RHO * C ** 2) / drv.Sd ** 2 * bl2
            lces = lces * lceb / (lces + lceb)
        e["Lces"] = lces
    else:  # closed-back tweeter: resonance from Fs and Qms
        res = drv.Re * drv.Qms / drv.Qes
        w0 = 2 * math.pi * drv.Fs
        e.update(Res=res, Cmes=drv.Qms / (w0 * res), Lces=res / (w0 * drv.Qms))
    return e


def z_equivalent(e, f):
    w = 2 * math.pi * f
    y = 1 / e["Res"] + 1 / (1j * w * e["Lces"]) + 1j * w * e["Cmes"]
    return e["Re"] + 1j * w * e["Le"] + 1 / y


def netlist(network, e, name):
    lines, n, k = [f"* {name} branch", "V1 n0 0 DC 0 AC 1"], 0, 0
    for pos, kind, val in network:
        k += 1
        if pos == "series":
            a, b = f"n{n}", f"n{n + 1}"
            n += 1
        else:
            a, b = f"n{n}", "0"
        if kind == "RC":
            lines += [f"R{k} {a} m{k} {val[0]:.6g}", f"C{k} m{k} {b} {val[1]:.6g}"]
        else:
            lines.append(f"{kind}{k} {a} {b} {val:.6g}")
    out = f"n{n}"
    lines += [f"RE {out} d1 {e['Re']:.6g}", f"LE d1 d2 {max(e['Le'], 1e-9):.6g}",
              f"RES d2 0 {e['Res']:.6g}", f"LCES d2 0 {e['Lces']:.6g}", f"CMES d2 0 {e['Cmes']:.6g}"]
    return lines, out


def run(r: dict, drivers: dict, f_check=None) -> dict:
    """r = simulate_design result (passive), drivers = {role: Driver}."""
    if r["design"]["crossover"]["mode"] != "passive":
        return {"available": False, "reason": "active crossover - no passive network to check"}
    f = np.geomspace(20, 20000, 121) if f_check is None else f_check
    from .system import _network_for  # re-built exactly like the simulation
    results, full = {}, []
    for role, net in _network_for(r).items():
        drv = drivers[role]
        box_L = r["metrics"]["net_volume_L"] if role == "woofer" and r["metrics"]["box_type"] == "sealed" else (
            r["chamber"]["Vb_L"] if role == "mid" and r.get("chamber") else None)
        e = equivalent(drv, box_L)
        lines, out = netlist(net, e, role)
        h_int, _ = xo.ladder(net, z_equivalent(e, f), f)
        with tempfile.TemporaryDirectory() as td:
            data = os.path.join(td, "out.txt")
            cir = "\n".join(lines + [".control", "ac dec 20 20 20000", f"wrdata {data} v({out})", "quit", ".endc", ".end"])
            p = subprocess.run(["ngspice", "-b"], input=cir, capture_output=True, text=True, timeout=60)
            if not os.path.exists(data):
                return {"available": False, "reason": "ngspice failed: " + (p.stderr or p.stdout)[-300:]}
            arr = np.loadtxt(data)
        fs, hs = arr[:, 0], arr[:, 1] + 1j * arr[:, 2]
        hi = np.interp(np.log(fs), np.log(f), np.abs(h_int))
        dev = float(np.max(np.abs(20 * np.log10(np.abs(hs) + 1e-12) - 20 * np.log10(hi + 1e-12))))
        results[role] = {"max_dev_db": round(dev, 3), "f": fs[::4].tolist(), "ngspice_db": (20 * np.log10(np.abs(hs[::4]))).tolist()}
        full += lines + [""]
    return {"available": True, "branches": results, "max_dev_db": max(v["max_dev_db"] for v in results.values()),
            "netlist": "\n".join(full)}
