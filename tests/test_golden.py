import json

import pytest
from golden.regen import GOLDEN, compute


@pytest.mark.science
def test_golden_seed42():
    expected = json.loads(GOLDEN.read_text())  # a missing golden fails, never skips
    actual = compute()
    assert len(actual) == len(expected)
    for a, e in zip(actual, expected, strict=True):
        assert a["pick_idx"] == e["pick_idx"]
        for key in ("x_km", "y_km", "t0"):
            assert a[key] == pytest.approx(e[key], rel=1e-6)
