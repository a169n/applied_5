import numpy as np
import pytest

from quakeloc.locate import Ellipse, LocationError, _jacobian, locate
from quakeloc.model import load_network, travel_time

net = load_network()


def exact_times(xy, t0=20.0):
    return t0 + travel_time(xy[0], xy[1], net.xy, net.h_km)


@pytest.mark.parametrize("xy", [(50, 50), (20, 70), (95, 55), (10, 15)])
def test_noise_free_exact_inversion(xy):
    sol = locate(net.xy, net.h_km, exact_times(xy))
    assert abs(sol.x_km - xy[0]) < 1e-6 and abs(sol.y_km - xy[1]) < 1e-6
    assert abs(sol.t0 - 20.0) < 1e-6
    assert sol.iterations <= 10


def test_constant_shift_moves_only_t0():
    a = locate(net.xy, net.h_km, exact_times((30, 40)))
    b = locate(net.xy, net.h_km, exact_times((30, 40)) + 3.0)
    assert b.x_km == pytest.approx(a.x_km, abs=1e-6) and b.y_km == pytest.approx(a.y_km, abs=1e-6)
    assert b.t0 == pytest.approx(a.t0 + 3.0, abs=1e-6)


def test_three_picks_raises():
    with pytest.raises(LocationError, match="4 picks"):
        locate(net.xy[:3], net.h_km[:3], exact_times((50, 50))[:3])


def test_collinear_raises():
    xy = np.column_stack([np.linspace(0, 100, 6), np.zeros(6)])
    t = 20 + travel_time(50, 30, xy, np.zeros(6))
    with pytest.raises(LocationError, match="collinear"):
        locate(xy, np.zeros(6), t)


def test_non_finite_time_raises():
    t = exact_times((50, 50))
    t[2] = np.nan
    with pytest.raises(LocationError, match="finite"):
        locate(net.xy, net.h_km, t)


def _negate_x(*args):
    g = _jacobian(*args).copy()
    g[:, 0] = -g[:, 0]
    return g


def test_wrong_jacobian_detected():
    try:
        sol = locate(net.xy, net.h_km, exact_times((30, 70)), jacobian=_negate_x)
    except LocationError:
        return
    assert np.hypot(sol.x_km - 30, sol.y_km - 70) > 1e-3


def test_uphill_jacobian_reports_stall():
    with pytest.raises(LocationError, match="stalled"):
        locate(net.xy, net.h_km, exact_times((30, 70)), jacobian=lambda *a: -_jacobian(*a))


def test_rank_deficient_jacobian_raises():
    def zero_column(*args):
        g = _jacobian(*args).copy()
        g[:, 1] = 0.0
        return g

    with pytest.raises(LocationError):
        locate(net.xy, net.h_km, exact_times((30, 70)), jacobian=zero_column)


def test_jacobian_matches_finite_differences():
    x, y, h = 33.0, 44.0, 1e-5
    g = _jacobian(x, y, net.xy, net.h_km)
    fd_x = (travel_time(x + h, y, net.xy, net.h_km) - travel_time(x - h, y, net.xy, net.h_km)) / (
        2 * h
    )
    fd_y = (travel_time(x, y + h, net.xy, net.h_km) - travel_time(x, y - h, net.xy, net.h_km)) / (
        2 * h
    )
    np.testing.assert_allclose(g[:, 0], fd_x, atol=1e-8)
    np.testing.assert_allclose(g[:, 1], fd_y, atol=1e-8)
    assert np.all(g[:, 2] == 1.0)


def test_known_sigma_ellipse_uses_chi2():
    sol = locate(net.xy, net.h_km, exact_times((50, 50)), sigma_s=0.02)
    g = _jacobian(sol.x_km, sol.y_km, net.xy, net.h_km)
    eig = np.linalg.eigvalsh(0.02**2 * np.linalg.inv(g.T @ g)[:2, :2])
    assert sol.ellipse.a_km**2 / eig[1] == pytest.approx(5.991, abs=1e-3)
    assert sol.ellipse.b_km**2 / eig[0] == pytest.approx(5.991, abs=1e-3)


def test_estimated_sigma_uses_f():
    rng = np.random.default_rng(1)
    t = exact_times((50, 50)) + rng.normal(0, 0.02, 8)
    sol = locate(net.xy, net.h_km, t)
    g = _jacobian(sol.x_km, sol.y_km, net.xy, net.h_km)
    r = t - (sol.t0 + travel_time(sol.x_km, sol.y_km, net.xy, net.h_km))
    s2 = np.sum(r**2) / 5
    eig = np.linalg.eigvalsh(s2 * np.linalg.inv(g.T @ g)[:2, :2])
    assert sol.ellipse.a_km**2 / eig[1] == pytest.approx(2 * 5.786, abs=2e-3)


def test_ellipse_azimuth_along_elongated_geometry():
    # Stations spread along x with little y aperture: y is poorly resolved, so the major
    # axis points north (azimuth near 0 or 180).
    xy = np.array([[-90, 0], [-50, 8], [-10, -8], [20, 10], [60, -10], [90, 5]], dtype=float)
    h = np.zeros(6)
    t = 20 + travel_time(0, 0, xy, h)
    sol = locate(xy, h, t, sigma_s=0.02)
    assert min(sol.ellipse.azimuth_deg, 180 - sol.ellipse.azimuth_deg) < 25
    assert sol.ellipse.a_km > sol.ellipse.b_km


def test_rms_zero_when_noise_free():
    assert locate(net.xy, net.h_km, exact_times((50, 50))).rms_s < 1e-6


def test_ellipse_contains():
    # Major axis 2 km pointing east (azimuth 90), minor axis 1 km.
    e = Ellipse(2.0, 1.0, 90.0)
    assert e.contains(1.9, 0.0) and not e.contains(2.1, 0.0)
    assert e.contains(0.0, 0.9) and not e.contains(0.0, 1.1)
