"""AIC onset picker (Maeda 1985)."""

import numpy as np

from quakeloc.detect import SignalError


def aic_pick(x, trigger_idx, fs, pre_s=3.0, post_s=1.0, m=10) -> int:
    """Return the index of the first sample of the signal segment."""
    start = max(0, trigger_idx - int(round(pre_s * fs)))
    w = np.asarray(x[start : trigger_idx + int(round(post_s * fs))], dtype=float)
    n = len(w)
    if n < 2 * m:
        raise SignalError(f"AIC window of {n} samples is shorter than {2 * m}")
    ks = np.arange(m, n - m + 1)
    # Variances of w[:k] and w[k:] for every k, from cumulative sums. Shifting by the window
    # mean first keeps round-off negligible for traces with a large offset.
    w = w - w.mean()
    c1 = np.concatenate([[0.0], np.cumsum(w)])
    c2 = np.concatenate([[0.0], np.cumsum(w**2)])
    head = c2[ks] / ks - (c1[ks] / ks) ** 2
    tail_n = n - ks
    tail = (c2[n] - c2[ks]) / tail_n - ((c1[n] - c1[ks]) / tail_n) ** 2
    # Round-off never gives exactly 0 for a constant segment, so compare to the window scale.
    if min(head.min(), tail.min()) <= 1e-12 * c2[n] / n:
        raise SignalError("zero variance in the AIC window")
    aic = ks * np.log(head) + tail_n * np.log(tail)
    return start + int(ks[np.argmin(aic)])
