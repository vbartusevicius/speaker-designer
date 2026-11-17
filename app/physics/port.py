"""Helmholtz port design: length, end correction, slot equivalents, velocity checks."""
from __future__ import annotations

import math

from .constants import C

END_CORR = {"flanged_free": 0.732, "flanged_both": 0.850, "free_both": 0.614}


def eq_diameter_mm(area_cm2: float) -> float:
    return math.sqrt(4 * area_cm2 * 100 / math.pi)


def port_length_mm(vb_L: float, fb: float, area_cm2_total: float, n_ports: int = 1,
                   end_correction: float = 0.732) -> float:
    """Physical length of each port.  fb = c/2pi * sqrt(Sp/(Vb*Leff)),  Leff = L + k*d."""
    sp = area_cm2_total * 1e-4
    vb = vb_L * 1e-3
    leff = C ** 2 * sp / ((2 * math.pi * fb) ** 2 * vb)
    d_each = eq_diameter_mm(area_cm2_total / n_ports) * 1e-3
    return (leff - end_correction * d_each) * 1000.0


def acoustic_length_mm(phys_len_mm: float, area_cm2_total: float, n_ports: int = 1,
                       end_correction: float = 0.732) -> float:
    return phys_len_mm + end_correction * eq_diameter_mm(area_cm2_total / n_ports)


def tuning_hz(vb_L: float, area_cm2_total: float, leff_mm: float) -> float:
    return C / (2 * math.pi) * math.sqrt(area_cm2_total * 1e-4 / (vb_L * 1e-3 * leff_mm * 1e-3))


def pipe_resonance_hz(leff_mm: float) -> float:
    return C / (2 * leff_mm * 1e-3)


def min_area_cm2(sd_cm2: float, xmax_mm: float, fb: float, n_drivers: int = 1, v_limit: float = 17.0) -> float:
    """Rule of thumb: port must carry cone volume velocity at fb with Xmax (peak) below v_limit."""
    return n_drivers * sd_cm2 * 1e-4 * xmax_mm * 1e-3 * 2 * math.pi * fb / v_limit * 1e4


# EU drain pipe (HT/KG, EN 1451 / EN 1401) sold in every DIY store, plus common flared port kits.
STANDARD_TUBES = [
    {"name": "HT DN40 pipe", "id": 36.4, "od": 40.0},
    {"name": "HT DN50 pipe", "id": 46.4, "od": 50.0},
    {"name": "HT DN75 pipe", "id": 71.2, "od": 75.0},
    {"name": "HT DN90 pipe", "id": 85.6, "od": 90.0},
    {"name": "HT DN110 pipe", "id": 104.6, "od": 110.0},
    {"name": "KG DN125 pipe", "id": 118.6, "od": 125.0},
]
FLARED_KITS = [
    {"name": "Flared port kit ID 50 mm", "id": 50.0, "od": 56.0},
    {"name": "Flared port kit ID 70 mm", "id": 70.0, "od": 76.0},
    {"name": "Flared port kit ID 100 mm", "id": 100.0, "od": 106.0},
]
