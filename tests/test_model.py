import math

import numpy as np
import pytest

from quakeloc.model import load_network, travel_time


def test_travel_time_analytic():
    t = travel_time(0, 0, np.array([[60.0, 0.0]]), np.zeros(1))
    assert t[0] == pytest.approx(math.sqrt(60**2 + 10**2) / 6, abs=1e-12)


def test_travel_time_elevation_km():
    t = travel_time(0, 0, np.array([[60.0, 0.0]]), np.array([3.4]))
    assert t[0] == pytest.approx(math.sqrt(60**2 + 13.4**2) / 6, abs=1e-12)


def test_network_loads_eight_noncollinear_stations():
    net = load_network()
    assert len(net.names) == 8 and net.xy.shape == (8, 2)
    centred = net.xy - net.xy.mean(axis=0)
    s = np.linalg.svd(centred, compute_uv=False)
    assert s[-1] / s[0] > 0.05
