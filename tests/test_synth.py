import numpy as np
import pytest

from quakeloc.model import Network, load_network, travel_time
from quakeloc.synth import DURATION_S, FS_HZ, PRE_S, event, noise, trace


def test_same_seed_identical():
    assert np.array_equal(trace(10, 30.0, 1), trace(10, 30.0, 1))


def test_different_seed_differs():
    assert not np.array_equal(trace(10, 30.0, 1), trace(10, 30.0, 2))


def test_trace_length_and_noise_unit_variance():
    x = noise(3)
    assert len(x) == int(DURATION_S * FS_HZ)
    assert x.std() == pytest.approx(1.0, abs=0.05)


def test_wavelet_causal_starts_at_offgrid_onset():
    onset = 30.004
    diff = trace(50, onset, 7) - noise(7)
    first = int(np.ceil(onset * FS_HZ))
    assert np.all(diff[:first] == 0)
    t = first / FS_HZ - onset
    assert diff[first] == pytest.approx(50 * np.sin(2 * np.pi * 5 * t) * np.exp(-t / 0.3))


def test_event_arrivals_match_model():
    ev = event(50, 50, 42, 8.0)
    tt = travel_time(50, 50, ev.network.xy, ev.network.h_km)
    assert ev.t0_s == PRE_S
    assert [ev.arrivals_s[n] for n in ev.network.names] == pytest.approx(list(PRE_S + tt))


def test_weakest_station_has_min_snr():
    ev = event(50, 50, 42, 8.0)
    assert min(ev.snrs.values()) == pytest.approx(8.0)


def test_snr_decays_with_distance():
    ev = event(10, 15, 42, 8.0)  # on top of ST01
    assert max(ev.snrs, key=ev.snrs.get) == "ST01"


def test_child_streams_independent_of_station_count():
    net = load_network()
    # The added station is near the source, so the weakest station (and the scale) is unchanged.
    extra = Network(
        net.names + ["NEW"],
        np.vstack([net.xy, [50.0, 50.0]]),
        np.append(net.h_km, 0.0),
    )
    a = event(50, 50, 42, 8.0, network=net)
    b = event(50, 50, 42, 8.0, network=extra)
    for name in net.names:
        assert np.array_equal(a.traces[name], b.traces[name])


def test_arrival_outside_window_raises():
    with pytest.raises(ValueError, match="arrival"):
        event(5000, 5000, 1, 5.0)
