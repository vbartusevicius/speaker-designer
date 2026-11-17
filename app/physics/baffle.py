"""Baffle edge-diffraction simulation (first-order edge sources, Vanderkooy/Urban style).

Same approach as VituixCAD's Diffraction tool and the "Edge" program: the driver is a
source on a rigid baffle; every perimeter element re-radiates an inverted secondary
wave with strength -1/2 * (angle subtended / 2pi).  The incident level at the edge is
weighted by the piston's 90-degree directivity, and an optional edge round-over
low-passes the diffracted wave.  Result is relative to half-space (2pi) radiation:
LF limit -6 dB (full space), HF -> 0 dB with ripple set by the driver position.
"""
from __future__ import annotations

import math
from typing import Optional, Sequence

import numpy as np

from .constants import C


def _perimeter(poly: np.ndarray, step_mm: float) -> tuple[np.ndarray, np.ndarray, np.ndarray]:
    pts, seg_a, seg_b = [], [], []
    for i in range(len(poly)):
        a, b = poly[i], poly[(i + 1) % len(poly)]
        L = float(np.hypot(*(b - a)))
        k = max(2, int(L / step_mm))
        t = (np.arange(k) + 0.5) / k
        mids = a + (b - a) * t[:, None]
        pts.append(mids)
        seg_a.append(a + (b - a) * (t - 0.5 / k)[:, None])
        seg_b.append(a + (b - a) * (t + 0.5 / k)[:, None])
    return np.vstack(pts), np.vstack(seg_a), np.vstack(seg_b)


def diffraction(f: np.ndarray, width_mm: float, height_mm: float, x_mm: float, y_mm: float,
                piston_radius_m: float, listener: Sequence[float], edge_radius_mm: float = 0.0,
                polygon: Optional[Sequence[Sequence[float]]] = None, step_mm: float = 4.0) -> np.ndarray:
    """Complex transfer function (relative to half space) at listener (x_mm, y_mm, dist_mm)."""
    poly = np.array(polygon if polygon is not None else
                    [[0, 0], [width_mm, 0], [width_mm, height_mm], [0, height_mm]], dtype=float) / 1000.0
    src = np.array([x_mm, y_mm]) / 1000.0
    lx, ly, lz = listener[0] / 1000.0, listener[1] / 1000.0, listener[2] / 1000.0
    pts, pa, pb = _perimeter(poly, step_mm / 1000.0)
    va, vb = pa - src, pb - src
    ang = np.abs(np.arctan2(va[:, 0] * vb[:, 1] - va[:, 1] * vb[:, 0], (va * vb).sum(1)))
    w = ang / ang.sum()  # source inside polygon -> sum = 2pi
    d = np.hypot(*(pts - src).T)
    e = np.sqrt((pts[:, 0] - lx) ** 2 + (pts[:, 1] - ly) ** 2 + lz ** 2)
    l0 = math.sqrt((src[0] - lx) ** 2 + (src[1] - ly) ** 2 + lz ** 2)
    k = 2 * math.pi * f / C
    ka = k * piston_radius_m
    directivity = 1.0 / np.sqrt(1.0 + ka ** 4 / 16.0)
    edge_lp = 1.0
    if edge_radius_mm > 0:
        fr = C / (2 * math.pi * edge_radius_mm / 1000.0) * 0.5
        edge_lp = 1.0 / np.sqrt(1.0 + (f / fr) ** 2)
    phase = np.exp(-1j * np.outer(k, d + e - l0))
    amp = w * (l0 / e)
    diff = (phase * amp).sum(axis=1)
    return 1.0 - 0.5 * directivity * edge_lp * diff


def baffle_step_f3(width_mm: float) -> float:
    """Classic rule of thumb: f3 of the baffle step = 115 / W[m]."""
    return 115.0 / (width_mm / 1000.0)
