"""Build tests/fixtures/mini_snapshot: a tiny SYNTHETIC snapshot in the real on-disk format.

Not real data. Run from the repository root when the snapshot format changes.
"""

import hashlib
import json
from pathlib import Path

import numpy as np

from quakeloc.geo import aeqd_forward, aeqd_inverse
from quakeloc.model import travel_time
from quakeloc.synth import trace

OUT = Path(__file__).parent / "mini_snapshot"
ORIGIN = (42.58, 74.78)
WINDOW = (-60.0, 120.0)
COUNTS_PER_UNIT = 100
STATIONS = {
    "AAA": (-60.0, -30.0, 900),
    "BBB": (50.0, -50.0, 1500),
    "CCC": (70.0, 40.0, 700),
    "DDD": (-20.0, 65.0, 2100),
    "EEE": (-70.0, 30.0, 1200),
    "FLT": (10.0, -75.0, 800),
    "NAN": (80.0, -10.0, 800),
}


def _meta(name, fs, channel="HHZ"):
    x, y, elevation = STATIONS[name]
    lat, lon = aeqd_inverse(x, y, *ORIGIN)
    return {
        "network": "XX",
        "station": name,
        "location": "",
        "channel": channel,
        "sampling_rate": fs,
        "lat": lat,
        "lon": lon,
        "elevation_m": elevation,
    }


def _signal(name, epicentre, fs, seed):
    x, y, elevation = STATIONS[name]
    xy = np.array([[x, y]])
    tt = float(travel_time(epicentre[0], epicentre[1], xy, np.array([elevation / 1000.0]))[0])
    return trace(30.0, -WINDOW[0] + tt, seed, fs=fs, duration_s=WINDOW[1] - WINDOW[0])


def _event(event_id, epicentre, rates, flat=(), with_nan=()):
    lat, lon = aeqd_inverse(*epicentre, *ORIGIN)
    meta, arrays = [], {}
    for i, (name, fs) in enumerate(rates.items()):
        meta.append(_meta(name, fs, "BHZ" if fs != 40.0 else "HHZ"))
        if name in flat:
            data = np.full(int((WINDOW[1] - WINDOW[0]) * fs), 1234, dtype=np.int32)
        else:
            data = np.rint(_signal(name, epicentre, fs, [11, i]) * COUNTS_PER_UNIT)
            data = data.astype(np.float32 if name in with_nan else np.int32)
            if name in with_nan:
                data[len(data) // 2] = np.nan
        arrays[name] = data
        arrays[f"{name}__start"] = np.array(WINDOW[0])
    summary = {
        "id": event_id,
        "time": "2020-01-01T00:00:00Z",
        "lat": lat,
        "lon": lon,
        "depth_km": 10.0,
        "magnitude": 4.5,
        "stations": meta,
    }
    return summary, arrays


def main():
    (OUT / "waveforms").mkdir(parents=True, exist_ok=True)
    events = [
        _event(
            "synth0001",
            (5.0, -8.0),
            {
                "AAA": 40.0,
                "BBB": 40.0,
                "CCC": 40.0,
                "DDD": 40.0,
                "EEE": 100.0,
                "FLT": 40.0,
                "NAN": 40.0,
            },
            flat=("FLT",),
            with_nan=("NAN",),
        ),
        _event(
            "synth0002",
            (-10.0, 12.0),
            {"AAA": 40.0, "BBB": 40.0, "CCC": 40.0, "FLT": 40.0},
            flat=("FLT",),
        ),
    ]
    for summary, arrays in events:
        np.savez_compressed(OUT / "waveforms" / f"{summary['id']}.npz", **arrays)
    (OUT / "events.json").write_text(json.dumps([e[0] for e in events], indent=2) + "\n")
    tracked = [OUT / "events.json", *sorted((OUT / "waveforms").glob("*.npz"))]
    manifest = {
        "description": "SYNTHETIC fixture for tests. Not real data.",
        "origin": {"lat": ORIGIN[0], "lon": ORIGIN[1]},
        "files": {
            p.relative_to(OUT).as_posix(): hashlib.sha256(p.read_bytes()).hexdigest()
            for p in tracked
        },
    }
    (OUT / "MANIFEST.json").write_text(json.dumps(manifest, indent=2, sort_keys=True) + "\n")
    assert aeqd_forward(*ORIGIN, *ORIGIN) == (0.0, 0.0)


if __name__ == "__main__":
    main()
