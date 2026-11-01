"""Preprocess, detect, pick and locate: the chain shared by every entry point."""

from dataclasses import dataclass

import numpy as np
from scipy import signal

from quakeloc.detect import Episode, SignalError, select_trigger, sta_lta, triggers
from quakeloc.locate import Solution, locate
from quakeloc.pick import aic_pick
from quakeloc.synth import FS_HZ, SynthEvent

_BAND_HZ = (2.0, 8.0)
_TAPER_S = 1.0


@dataclass(frozen=True)
class PickResult:
    episodes: list[Episode]
    trigger_idx: int | None
    pick_idx: int | None


@dataclass(frozen=True)
class ChainResult:
    solution: Solution
    picks: dict[str, float]
    skipped: dict[str, str]


def preprocess_real(x, fs) -> np.ndarray:
    """Demean, 1 s cosine taper at both ends, causal 2-8 Hz Butterworth band-pass."""
    if fs <= 2 * _BAND_HZ[1]:
        raise SignalError(f"sampling rate {fs} Hz is too low for the {_BAND_HZ} Hz band")
    y = np.asarray(x, dtype=float)
    y = y - y.mean()
    n = int(round(_TAPER_S * fs))
    if len(y) < 2 * n:
        raise SignalError("trace is shorter than the taper")
    ramp = 0.5 * (1 - np.cos(np.pi * np.arange(n) / n))
    y[:n] *= ramp
    y[-n:] *= ramp[::-1]
    sos = signal.butter(2, _BAND_HZ, btype="bandpass", fs=fs, output="sos")
    return signal.sosfilt(sos, y)


def pick_trace(x, fs, on, blank_s=0.0) -> PickResult:
    """Detect and pick one trace. ``blank_s`` forces the ratio to 0 at the start."""
    ratio, _ = sta_lta(x, fs)
    ratio[: int(round(blank_s * fs))] = 0.0
    episodes = triggers(ratio, on)
    selected = select_trigger(episodes)
    if selected is None:
        return PickResult(episodes, None, None)
    return PickResult(episodes, selected.on_idx, aic_pick(x, selected.on_idx, fs))


def locate_synth(event: SynthEvent, on) -> ChainResult:
    """Full chain on a synthetic event. Raises LocationError if it cannot be located."""
    net = event.network
    picks, skipped = {}, {}
    for name in net.names:
        try:
            result = pick_trace(event.traces[name], FS_HZ, on)
        except SignalError as exc:
            skipped[name] = str(exc)
            continue
        if result.pick_idx is None:
            skipped[name] = "no detection"
        else:
            picks[name] = result.pick_idx / FS_HZ
    keep = [i for i, name in enumerate(net.names) if name in picks]
    times = [picks[net.names[i]] for i in keep]
    return ChainResult(locate(net.xy[keep], net.h_km[keep], times), picks, skipped)
