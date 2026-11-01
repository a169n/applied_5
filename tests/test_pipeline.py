import numpy as np
import pytest

from quakeloc.detect import SignalError
from quakeloc.pipeline import locate_synth, pick_trace, preprocess_real
from quakeloc.synth import FS_HZ, event, noise, trace


def test_preprocess_is_causal():
    x = noise(1)
    k = 3000
    y = x.copy()
    y[k] += 1.0
    y[k + 1] -= 1.0  # same mean, so demeaning cancels
    diff = preprocess_real(y, FS_HZ) - preprocess_real(x, FS_HZ)
    assert np.max(np.abs(diff[:k])) < 1e-12
    assert np.max(np.abs(diff[k:])) > 1e-3


def test_preprocess_removes_offset_and_keeps_band():
    x = 1000.0 + noise(2)
    assert abs(preprocess_real(x, FS_HZ)[1500:].mean()) < 0.05


def test_preprocess_rejects_rate_below_band():
    with pytest.raises(SignalError, match="sampling rate"):
        preprocess_real(noise(1, fs=10.0), 10.0)


def test_blanking_suppresses_early_trigger():
    x = trace(50, 12.0, 3)
    assert pick_trace(x, FS_HZ, 2.0).pick_idx is not None
    assert pick_trace(x, FS_HZ, 2.0, blank_s=15.0).pick_idx is None


def test_no_detection_returns_none():
    r = pick_trace(noise(4), FS_HZ, 50.0)
    assert r.episodes == [] and r.trigger_idx is None and r.pick_idx is None


def test_pick_trace_finds_onset():
    r = pick_trace(trace(15, 30.0, 5), FS_HZ, 2.0)
    assert abs(r.pick_idx / FS_HZ - 30.0) < 0.1


def test_locate_synth_recovers_epicentre():
    ev = event(50, 50, 42, 10.0)
    r = locate_synth(ev, 2.0)
    assert np.hypot(r.solution.x_km - 50, r.solution.y_km - 50) < 1.0
    assert r.skipped == {}
    assert set(r.picks) == set(ev.network.names)
