"""Classic energy STA/LTA trigger (Allen 1978; Withers et al. 1998)."""

from dataclasses import dataclass

import numpy as np

STA_S = 0.5
LTA_S = 10.0
OFF = 1.5


class SignalError(ValueError):
    """The waveform cannot be processed (flat, dead, non-finite or too short)."""


@dataclass(frozen=True)
class Episode:
    on_idx: int
    off_idx: int
    peak: float


def _window_lengths(fs):
    n_sta, n_lta = int(round(STA_S * fs)), int(round(LTA_S * fs))
    if n_sta < 1:
        raise SignalError(f"sampling rate {fs} Hz is too low for a {STA_S} s STA window")
    return n_sta, n_lta


def _check(x, n_lta):
    x = np.asarray(x, dtype=float)
    if len(x) < n_lta:
        raise SignalError(f"trace of {len(x)} samples is shorter than the LTA window")
    if not np.all(np.isfinite(x)):
        raise SignalError("trace contains non-finite samples")
    if np.ptp(x) == 0:
        raise SignalError("flat trace")
    return x


def sta_lta(x, fs) -> tuple[np.ndarray, int]:
    """Return the STA/LTA ratio (0 before ``valid_from``) and ``valid_from = n_lta - 1``."""
    n_sta, n_lta = _window_lengths(fs)
    x = _check(x, n_lta)
    cum = np.concatenate([[0.0], np.cumsum(x**2)])
    valid_from = n_lta - 1
    lta = (cum[n_lta:] - cum[:-n_lta]) / n_lta
    sta = (cum[n_lta:] - cum[n_lta - n_sta : -n_sta]) / n_sta
    # Compare against the trace's energy scale: a cumulative sum never returns exactly 0.
    if lta.min() <= 1e-12 * lta.max():
        raise SignalError("LTA is zero: dead segment in the trace")
    ratio = np.zeros(len(x))
    ratio[valid_from:] = sta / lta
    return ratio, valid_from


def sta_lta_naive(x, fs) -> tuple[np.ndarray, int]:
    """Double-loop reference implementation; a test oracle only."""
    n_sta, n_lta = _window_lengths(fs)
    x = _check(x, n_lta)
    ratio = np.zeros(len(x))
    for i in range(n_lta - 1, len(x)):
        sta = sum(v * v for v in x[i - n_sta + 1 : i + 1]) / n_sta
        lta = sum(v * v for v in x[i - n_lta + 1 : i + 1]) / n_lta
        ratio[i] = sta / lta
    return ratio, n_lta - 1


def triggers(ratio, on, off=OFF) -> list[Episode]:
    """Hysteresis: an episode opens at ``ratio >= on`` and closes at ``ratio < off``."""
    episodes = []
    ratio = np.asarray(ratio)
    n, i = len(ratio), 0
    while i < n:
        above = np.flatnonzero(ratio[i:] >= on)
        if not len(above):
            break
        start = i + int(above[0])
        below = np.flatnonzero(ratio[start:] < off)
        end = start + int(below[0]) if len(below) else n - 1
        episodes.append(Episode(start, end, float(ratio[start : end + 1].max())))
        i = end + 1
    return episodes


def select_trigger(episodes) -> Episode | None:
    """Earliest episode whose peak is at least half the global maximum (prefers P over S)."""
    if not episodes:
        return None
    peak = max(e.peak for e in episodes)
    return next(e for e in episodes if e.peak >= 0.5 * peak)
