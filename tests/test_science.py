"""Scientific validation: statistical calibration of uncertainty and detection."""

import numpy as np
import pytest

from quakeloc.calibrate import calibrate
from quakeloc.locate import locate
from quakeloc.model import load_network, travel_time

net = load_network()
PICK_SIGMA_S = 0.02
TRIALS = 200
pytestmark = pytest.mark.science


@pytest.mark.parametrize("mode", ["known", "estimated"])
@pytest.mark.parametrize("region", ["inside", "outside"])
def test_ellipse_coverage(mode, region):
    rng = np.random.default_rng(np.random.SeedSequence([7, TRIALS]))
    inside = 0
    for _ in range(TRIALS):
        x = rng.uniform(15, 85) if region == "inside" else rng.uniform(110, 150)
        y = rng.uniform(15, 85)
        t = 20.0 + travel_time(x, y, net.xy, net.h_km) + rng.normal(0, PICK_SIGMA_S, 8)
        sol = locate(net.xy, net.h_km, t, sigma_s=PICK_SIGMA_S if mode == "known" else None)
        inside += sol.ellipse.contains(x - sol.x_km, y - sol.y_km)
    assert 0.90 <= inside / TRIALS <= 0.99


def test_recall_snr5_at_far_1pct(tmp_path):
    assert calibrate(42, tmp_path)["recall_snr5"] >= 0.95
