import numpy as np
import pytest

from quakeloc.detect import (
    Episode,
    SignalError,
    select_trigger,
    sta_lta,
    sta_lta_naive,
    triggers,
)
from quakeloc.synth import FS_HZ, noise, trace


@pytest.mark.parametrize("snr", [0, 5, 100])
def test_vectorised_matches_naive(snr):
    x = trace(snr, 30.0, 11, duration_s=25.0) if snr == 0 else trace(snr, 15.0, 11, duration_s=25.0)
    ratio, valid_from = sta_lta(x, FS_HZ)
    naive, naive_from = sta_lta_naive(x, FS_HZ)
    assert valid_from == naive_from == 999
    np.testing.assert_allclose(ratio, naive, rtol=1e-9, atol=1e-12)


def test_ratio_zero_before_valid_from():
    ratio, valid_from = sta_lta(noise(1), FS_HZ)
    assert np.all(ratio[:valid_from] == 0) and ratio[valid_from] > 0


def test_amplitude_scale_invariant():
    x = trace(10, 30.0, 2)
    a, _ = sta_lta(x, FS_HZ)
    b, _ = sta_lta(1000 * x, FS_HZ)
    np.testing.assert_allclose(a, b, rtol=1e-9, atol=1e-12)


def test_noise_mean_near_one():
    ratio, valid_from = sta_lta(noise(5), FS_HZ)
    assert abs(ratio[valid_from:].mean() - 1) <= 0.05


@pytest.mark.parametrize(
    "x",
    [
        np.zeros(6000),
        np.full(6000, 7.0),
        np.concatenate([np.zeros(3000), noise(1, 30.0)]),
        np.ones(10),
        np.concatenate([noise(1, 30.0), [np.nan], noise(2, 30.0)]),
    ],
    ids=["zeros", "constant", "dead_segment", "too_short", "nan"],
)
def test_unusable_input_raises(x):
    with pytest.raises(SignalError):
        sta_lta(x, FS_HZ)


def test_hysteresis_episodes():
    ratio = np.array([1, 1, 3, 4, 2, 1.4, 1, 2.5, 3, 1, 1], dtype=float)
    assert triggers(ratio, on=2.5) == [Episode(2, 5, 4.0), Episode(7, 9, 3.0)]


def test_episode_open_at_end():
    ratio = np.array([1, 3, 4, 3], dtype=float)
    assert triggers(ratio, on=2.5) == [Episode(1, 3, 4.0)]


def test_no_episode_below_threshold():
    assert triggers(np.ones(10), on=2.5) == []


def test_select_prefers_early_p_over_stronger_s():
    eps = [Episode(100, 200, 6.0), Episode(500, 700, 10.0)]
    assert select_trigger(eps).on_idx == 100


def test_select_skips_weak_early():
    eps = [Episode(100, 200, 3.0), Episode(500, 700, 10.0)]
    assert select_trigger(eps).on_idx == 500


def test_select_empty_is_none():
    assert select_trigger([]) is None


def test_energy_overflow_raises():
    x = noise(1)
    x[3000] = 1e160
    with pytest.raises(SignalError, match="overflow"):
        sta_lta(x, FS_HZ)
