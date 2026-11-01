"""Seeded detector calibration. Outputs are a pure function of the inputs."""

import argparse
import hashlib
import json
from pathlib import Path

import numpy as np

from quakeloc.detect import SignalError, sta_lta, triggers
from quakeloc.locate import LocationError
from quakeloc.pipeline import locate_synth, pick_trace, preprocess_real
from quakeloc.synth import FS_HZ, event, noise, trace

_FAR_MAX = 0.01
_GRID = [round(1.6 + 0.05 * i, 2) for i in range(149)]  # 1.6 ... 9.0
_REAL_WINDOW_S, _REAL_TRANSIENT_S = 50.0, 15.0
_TRACE_ONSET_S = (25.0, 50.0)


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _input_hashes() -> dict[str, str]:
    files = [
        p
        for root in ("src", "config")
        for p in Path(root).rglob("*")
        if p.suffix in (".py", ".json")
    ]
    return {p.as_posix(): _sha256(p) for p in sorted(files)}


def _smallest_threshold(max_ratios: np.ndarray) -> float:
    for th in _GRID:
        if np.mean(max_ratios >= th) <= _FAR_MAX:
            return th
    raise ValueError("no threshold on the grid reaches the false-alarm target")


def _calibrate_realdata(seed, n_noise) -> float:
    """FAR <= 1 % per 50 s window on noise passed through the real preprocessing."""
    maxima = []
    for i in range(n_noise):
        x = preprocess_real(noise([seed, 2, i], _REAL_WINDOW_S + _REAL_TRANSIENT_S), FS_HZ)
        ratio, _ = sta_lta(x, FS_HZ)
        maxima.append(ratio[int(_REAL_TRANSIENT_S * FS_HZ) :].max())
    return _smallest_threshold(np.array(maxima))


def _calibrate_raw(seed, n_traces, n_noise):
    rng = np.random.default_rng(np.random.SeedSequence([seed, 0]))
    snrs = rng.uniform(3.0, 20.0, n_traces)
    onsets = rng.uniform(*_TRACE_ONSET_S, n_traces)
    signal_ratios = [
        sta_lta(trace(s, o, [seed, 1, i]), FS_HZ)[0]
        for i, (s, o) in enumerate(zip(snrs, onsets, strict=True))
    ]
    noise_ratios = [sta_lta(noise([seed, 3, i]), FS_HZ)[0] for i in range(n_noise)]

    best = None
    for th in _GRID:
        false_windows = sum(bool(triggers(r, th)) for r in noise_ratios)
        if false_windows / n_noise > _FAR_MAX:
            continue
        hits, false_alarms = np.zeros(n_traces, dtype=bool), false_windows
        for i, ratio in enumerate(signal_ratios):
            lo, hi = (onsets[i] - 0.2) * FS_HZ, (onsets[i] + 1.0) * FS_HZ
            for episode in triggers(ratio, th):
                if lo <= episode.on_idx <= hi:
                    hits[i] = True
                else:
                    false_alarms += 1
        tp = int(hits.sum())
        precision = tp / (tp + false_alarms) if tp + false_alarms else 0.0
        recall = tp / n_traces
        f1 = 2 * precision * recall / (precision + recall) if tp else 0.0
        if best is None or f1 > best["f1"]:
            strong = snrs >= 5.0
            best = {
                "f1": f1,
                "on_raw": th,
                "precision": precision,
                "recall": recall,
                "recall_snr5": float(hits[strong].mean()) if strong.any() else 0.0,
            }
    if best is None:
        raise ValueError("no threshold on the grid reaches the false-alarm target")
    return best, snrs, onsets


def _pick_errors(seed, on, snrs, onsets) -> np.ndarray:
    errors = []
    for i, (s, o) in enumerate(zip(snrs, onsets, strict=True)):
        try:
            idx = pick_trace(trace(s, o, [seed, 1, i]), FS_HZ, on).pick_idx
        except SignalError:
            continue
        if idx is not None and abs(idx / FS_HZ - o) <= 1.0:
            errors.append(idx / FS_HZ - o)
    return np.array(errors) if errors else np.zeros(1)


def _location_benchmark(seed, on, n_events):
    rng = np.random.default_rng(np.random.SeedSequence([seed, 4]))
    errors, failures = [], 0
    for i in range(n_events):
        x, y = rng.uniform(10.0, 90.0, 2)
        min_snr = rng.uniform(5.0, 20.0)
        try:
            sol = locate_synth(event(x, y, [seed, 5, i], min_snr), on).solution
        except LocationError:
            failures += 1
            continue
        errors.append(float(np.hypot(sol.x_km - x, sol.y_km - y)))
    return (float(np.mean(errors)) if errors else None), failures


def calibrate(seed, out_dir, n_traces=150, n_noise=150, n_events=50) -> dict:
    out = Path(out_dir)
    out.mkdir(parents=True, exist_ok=True)
    best, snrs, onsets = _calibrate_raw(seed, n_traces, n_noise)
    on = best["on_raw"]
    err = _pick_errors(seed, on, snrs, onsets)
    median = float(np.median(err))
    mean_loc, failures = _location_benchmark(seed, on, n_events)
    detector = {
        "on_raw": on,
        "on_realdata": _calibrate_realdata(seed, n_noise),
        "precision": best["precision"],
        "recall": best["recall"],
        "recall_snr5": best["recall_snr5"],
        "pick_err_median_s": median,
        "pick_err_mad_s": float(np.median(np.abs(err - median))),
        "mean_loc_err_km": mean_loc,
        "location_errors": failures,
    }
    detector_path = out / "detector.json"
    detector_path.write_text(json.dumps(detector, indent=2, sort_keys=True) + "\n")
    manifest = {
        "seed": seed,
        "numpy": np.__version__,
        "sizes": {"n_traces": n_traces, "n_noise": n_noise, "n_events": n_events},
        "inputs": _input_hashes(),
        "outputs": {"detector.json": _sha256(detector_path)},
    }
    (out / "manifest.json").write_text(json.dumps(manifest, indent=2, sort_keys=True) + "\n")
    return detector


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--seed", type=int, default=42)
    parser.add_argument("--out", default="artifacts")
    parser.add_argument("--tiny", action="store_true", help="tiny sample sizes, for tests")
    args = parser.parse_args(argv)
    sizes = dict(n_traces=12, n_noise=12, n_events=3) if args.tiny else {}
    print(json.dumps(calibrate(args.seed, args.out, **sizes), indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
