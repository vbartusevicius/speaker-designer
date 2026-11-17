import math

import numpy as np

from app.design import drivers_db
from app.physics import crossover as xo
from app.physics.alignments import optimise_vented, qb3, sealed_for_qtc
from app.physics.baffle import diffraction
from app.physics.enclosure import Box, freq_axis, simulate
from app.physics.port import port_length_mm, tuning_hz


def sb23():
    return drivers_db.get("sb-sb23nrxs45-8")


def test_derived_ts_match_datasheet():
    d = sb23()
    assert abs(d.Mms * 1e3 - 24.5) < 0.5
    assert abs(d.Bl - 7.5) < 0.2
    assert abs(d.Cms * 1e3 - 1.42) < 0.02


def test_sealed_qtc_formula():
    d = sb23()
    r = sealed_for_qtc(d, 0.707)
    alpha = (0.707 / d.Qts) ** 2 - 1
    assert math.isclose(r["Vb_L"], d.Vas_L / alpha, rel_tol=1e-9)


def test_vented_optimum_close_to_qb3_and_manufacturer():
    d = sb23()
    q = qb3(d)
    v = optimise_vented(d, q["Vb_L"], fill=0)
    assert abs(v["fb"] - q["fb"]) < 2.0
    assert abs(v["f3"] - q["f3"]) < 2.5
    # SB Acoustics recommends 58 L @ 30 Hz
    assert abs(optimise_vented(d, 58, fill=0)["fb"] - 30) <= 1.5


def test_port_length_roundtrip():
    L = port_length_mm(50, 32, 50.0, 1, 0.732)
    d = math.sqrt(4 * 5000 / math.pi)
    assert abs(tuning_hz(50, 50.0, L + 0.732 * d) - 32) < 0.01


def test_vented_impedance_has_minimum_near_fb():
    d = sb23()
    f = freq_axis(10, 200, 600)
    leff = port_length_mm(55, 30, 50, 1, 0.0)
    s = simulate(d, Box("vented", 55, 30, 50, leff, Ql=50, Qp=200), f, use_le=False)
    z = np.abs(s.zin)
    band = (f > 15) & (f < 60)
    fmin = f[band][np.argmin(z[band])]
    assert abs(fmin - 30) < 3


def test_diffraction_limits():
    f = np.array([10.0, 20000.0])
    D = diffraction(f, 400, 400, 200, 200, 0.05, (200, 200, 3000))
    assert abs(20 * np.log10(abs(D[0])) + 6.02) < 0.3  # full-space at LF
    assert abs(20 * np.log10(abs(D[1]))) < 1.5  # half-space at HF


def test_lr4_sums_flat():
    f = freq_axis(20, 20000, 200)
    s = xo.lr4_lp(f, 1000) + xo.lr4_hp(f, 1000)
    assert np.allclose(np.abs(s), 1.0, atol=1e-9)


def test_ladder_lr2_matches_ideal_on_resistive_load():
    f = freq_axis(20, 20000, 200)
    L, C = xo.passive_lc(2000, 8.0, "LR2")
    h, _ = xo.ladder([("series", "L", L), ("shunt", "C", C)], np.full_like(f, 8.0, dtype=complex), f)
    assert np.allclose(h, xo.lr2_lp(f, 2000), atol=1e-6)


def test_minimum_phase_matches_analytic_highpass():
    from app.design.measurements import minimum_phase
    f = freq_axis(20, 20000, 300)
    s = 1j * f / 1000.0
    h = s ** 2 / (s ** 2 + s / 0.707 + 1)  # 2nd-order high-pass is minimum phase
    ph = minimum_phase(f, 20 * np.log10(np.abs(h)))
    m = (f > 200) & (f < 8000)
    err = np.angle(np.exp(1j * (ph[m] - np.angle(h[m]))))
    assert np.max(np.abs(np.degrees(err))) < 6
