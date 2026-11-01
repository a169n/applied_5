import numpy as np
import pytest
from hypothesis import assume, given
from hypothesis import strategies as st

from quakeloc.detect import SignalError, select_trigger, sta_lta, triggers
from quakeloc.pick import aic_pick
from quakeloc.synth import FS_HZ, noise, trace

ON = 2.0


def _pick(x, on=ON):
    ratio, _ = sta_lta(x, FS_HZ)
    episodes = triggers(ratio, on)
    selected = select_trigger(episodes)
    return (None if selected is None else aic_pick(x, selected.on_idx, FS_HZ)), episodes


def test_pick_error_percentiles():
    rng = np.random.default_rng(2024)
    errors = []
    for seed in range(200):
        onset = float(rng.uniform(25.0, 50.0))
        idx, _ = _pick(trace(10, onset, seed))
        errors.append(abs(idx / FS_HZ - onset))
    err = np.array(errors)
    assert np.percentile(err, 95) <= 0.04
    assert np.percentile(err, 99) <= 0.15
    assert err.max() <= 0.3


def test_short_window_raises():
    with pytest.raises(SignalError, match="window"):
        aic_pick(noise(1)[:15], 5, FS_HZ)


def test_zero_variance_raises():
    x = noise(1)
    x[2000:2200] = 3.0
    with pytest.raises(SignalError, match="variance"):
        aic_pick(x, 2100, FS_HZ)


def test_window_clipped_at_trace_start():
    x = trace(20, 0.5, 3, duration_s=5.0)
    idx = aic_pick(x, 60, FS_HZ)
    assert abs(idx / FS_HZ - 0.5) < 0.1


def test_pick_is_first_sample_of_signal_segment():
    x = trace(1000, 30.0, 4)
    assert aic_pick(x, 3005, FS_HZ) in range(3000, 3004)


@given(st.integers(0, 2000))
def test_shift_equivariance(k):
    onset, seed = 30.004, 77
    x = trace(10, onset, seed)
    prefix = noise(seed + 1, 20.0)[:k]
    base, _ = _pick(x)
    shifted, episodes = _pick(np.concatenate([prefix, x]))
    assume(all(e.on_idx >= k + (onset - 3.0) * FS_HZ for e in episodes))
    assert shifted == base + k
