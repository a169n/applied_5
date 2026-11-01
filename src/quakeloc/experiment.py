"""SNR sweep through the full waveform chain. Reported, not gated."""

import argparse
import csv
import json
from pathlib import Path

import numpy as np

from quakeloc.locate import LocationError
from quakeloc.pipeline import locate_synth
from quakeloc.synth import event

COLUMNS = ["snr", "recall", "pick_err_s", "loc_err_km", "coverage"]
_SEEDS = list(range(40))
_SNRS = [3.0, 4.0, 5.0, 7.0, 10.0, 15.0, 20.0]
_PICK_MATCH_S = 1.0


def _mean(values):
    return float(np.mean(values)) if values else None


def sweep(seeds, snrs, on, out_csv) -> list[dict]:
    rows = []
    for snr in snrs:
        hits, stations, pick_err, loc_err, covered = 0, 0, [], [], []
        for seed in seeds:
            rng = np.random.default_rng(np.random.SeedSequence([seed, 6]))
            x, y = rng.uniform(15.0, 85.0, 2)
            ev = event(x, y, [seed, 7, int(snr * 10)], snr)
            stations += len(ev.network.names)
            try:
                result = locate_synth(ev, on)
            except LocationError:
                continue
            errors = [abs(t - ev.arrivals_s[name]) for name, t in result.picks.items()]
            good = [e for e in errors if e <= _PICK_MATCH_S]
            hits += len(good)
            pick_err += good
            sol = result.solution
            loc_err.append(float(np.hypot(sol.x_km - x, sol.y_km - y)))
            covered.append(sol.ellipse.contains(x - sol.x_km, y - sol.y_km))
        rows.append(
            {
                "snr": snr,
                "recall": hits / stations,
                "pick_err_s": float(np.median(pick_err)) if pick_err else None,
                "loc_err_km": _mean(loc_err),
                "coverage": _mean(covered),
            }
        )
    out = Path(out_csv)
    out.parent.mkdir(parents=True, exist_ok=True)
    with out.open("w", newline="") as f:
        writer = csv.DictWriter(f, COLUMNS)
        writer.writeheader()
        writer.writerows(rows)
    return rows


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--artifacts", default="artifacts")
    parser.add_argument("--out", default="artifacts/snr_sweep.csv")
    parser.add_argument("--tiny", action="store_true", help="tiny sweep, for tests")
    args = parser.parse_args(argv)
    on = json.loads((Path(args.artifacts) / "detector.json").read_text())["on_raw"]
    seeds, snrs = ([1], [10.0]) if args.tiny else (_SEEDS, _SNRS)
    for row in sweep(seeds, snrs, on, args.out):
        print(row)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
