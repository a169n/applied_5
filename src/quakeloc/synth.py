"""Seeded synthetic seismograms with a known true answer."""

from dataclasses import dataclass

import numpy as np

from quakeloc.model import Network, load_network, travel_time

FS_HZ = 100.0
DURATION_S = 60.0
PRE_S = 20.0  # the trace starts at t0 - PRE_S
_MIN_ARRIVAL_S, _MAX_ARRIVAL_S = 13.0, 58.0
_FREQ_HZ, _DECAY_S = 5.0, 0.3


@dataclass(frozen=True)
class SynthEvent:
    traces: dict[str, np.ndarray]
    arrivals_s: dict[str, float]  # seconds from trace start
    t0_s: float
    snrs: dict[str, float]
    network: Network


def _noise(rng, duration_s, fs):
    return rng.standard_normal(int(round(duration_s * fs)))


def _add_wavelet(x, amplitude, onset_s, fs):
    """Add the causal wavelet starting exactly at the (off-grid) onset time."""
    first = int(np.ceil(onset_s * fs))
    t = np.arange(first, len(x)) / fs - onset_s
    x[first:] += amplitude * np.sin(2 * np.pi * _FREQ_HZ * t) * np.exp(-t / _DECAY_S)
    return x


def noise(seed, duration_s=DURATION_S, fs=FS_HZ) -> np.ndarray:
    return _noise(np.random.default_rng(np.random.SeedSequence(seed)), duration_s, fs)


def trace(snr, onset_s, seed, fs=FS_HZ, duration_s=DURATION_S) -> np.ndarray:
    """Single trace: unit-variance white noise plus a wavelet of amplitude ``snr``."""
    return _add_wavelet(noise(seed, duration_s, fs), snr, onset_s, fs)


def event(x_km, y_km, seed, min_snr, network: Network | None = None) -> SynthEvent:
    """Multi-station event; amplitude decays as 1/r, weakest station has ``min_snr``."""
    net = network or load_network()
    tt = travel_time(x_km, y_km, net.xy, net.h_km)
    arrivals = PRE_S + tt
    if arrivals.min() < _MIN_ARRIVAL_S or arrivals.max() > _MAX_ARRIVAL_S:
        raise ValueError(f"arrival outside [{_MIN_ARRIVAL_S}, {_MAX_ARRIVAL_S}] s of the trace")
    snrs = min_snr * tt.max() / tt  # distance is proportional to travel time
    children = np.random.SeedSequence(seed).spawn(len(net.names))
    traces = {
        name: _add_wavelet(_noise(np.random.default_rng(c), DURATION_S, FS_HZ), s, a, FS_HZ)
        for name, c, s, a in zip(net.names, children, snrs, arrivals, strict=True)
    }
    return SynthEvent(
        traces=traces,
        arrivals_s=dict(zip(net.names, arrivals.tolist(), strict=True)),
        t0_s=PRE_S,
        snrs=dict(zip(net.names, snrs.tolist(), strict=True)),
        network=net,
    )
