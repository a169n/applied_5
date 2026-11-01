"""Regenerate the seed-42 golden. Run only through ``make golden``, in a reviewed commit."""

import json
from pathlib import Path

from quakeloc.pipeline import locate_synth
from quakeloc.synth import FS_HZ, event

GOLDEN = Path(__file__).parent / "seed42.json"
ON = 2.0
CASES = [(50.0, 50.0, 10.0), (30.0, 70.0, 6.0)]


def compute() -> list[dict]:
    out = []
    for x, y, min_snr in CASES:
        r = locate_synth(event(x, y, 42, min_snr), ON)
        out.append(
            {
                "input": [x, y, min_snr],
                "pick_idx": {k: round(v * FS_HZ) for k, v in r.picks.items()},
                "x_km": r.solution.x_km,
                "y_km": r.solution.y_km,
                "t0": r.solution.t0,
            }
        )
    return out


if __name__ == "__main__":
    GOLDEN.write_text(json.dumps(compute(), indent=2, sort_keys=True) + "\n")
