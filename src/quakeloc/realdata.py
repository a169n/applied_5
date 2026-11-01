"""Process a checksummed real-data snapshot and compare with the USGS catalog."""

import argparse
import csv
import hashlib
import json
from dataclasses import dataclass, field
from pathlib import Path

import numpy as np

from quakeloc.detect import SignalError
from quakeloc.geo import aeqd_forward, aeqd_inverse, haversine_km
from quakeloc.locate import LocationError, Solution, locate
from quakeloc.model import travel_time
from quakeloc.pipeline import pick_trace, preprocess_real

BLANK_S = 15.0  # taper + filter settling + LTA warm-up
_FALSE_TRIGGER_START_S = 20.0
_FALSE_TRIGGER_END_S = -5.0  # relative to the origin time
_MAX_RESIDUAL_S = 1.5
_MIN_PICKS_TO_REJECT = 5
_GATE_HEADROOM = 1.5

CSV_COLUMNS = [
    "event_id",
    "located",
    "reason",
    "lat",
    "lon",
    "t0_s",
    "a_km",
    "b_km",
    "azimuth_deg",
    "rms_s",
    "used",
    "rejected",
    "skipped",
    "mislocation_km",
    "dt0_s",
    "false_triggers",
]


class SnapshotError(ValueError):
    """The snapshot is missing a file or fails its checksums."""


@dataclass(frozen=True)
class Snapshot:
    root: Path
    events: list[dict]
    origin: dict
    manifest_hash: str


@dataclass(frozen=True)
class EventResult:
    event_id: str
    located: bool
    reason: str = ""
    lat: float | None = None
    lon: float | None = None
    t0: float | None = None  # seconds relative to the catalog origin time
    ellipse: object | None = None
    rms_s: float | None = None
    used: list[str] = field(default_factory=list)
    rejected: dict[str, float] = field(default_factory=dict)
    skipped: dict[str, str] = field(default_factory=dict)
    mislocation_km: float | None = None
    dt0_s: float | None = None
    false_triggers: dict[str, int] = field(default_factory=dict)


def has_snapshot(root) -> bool:
    return (Path(root) / "MANIFEST.json").exists()


def load_snapshot(root) -> Snapshot:
    root = Path(root)
    manifest_path = root / "MANIFEST.json"
    if not manifest_path.exists():
        raise SnapshotError(f"no MANIFEST.json in {root}")
    raw = manifest_path.read_bytes()
    try:
        manifest = json.loads(raw)
        files, origin = manifest["files"].items(), manifest["origin"]
    except (ValueError, KeyError, TypeError, AttributeError) as exc:
        raise SnapshotError(f"MANIFEST.json is unreadable: {exc}") from exc
    for name, expected in files:
        path = root / name
        if not path.exists():
            raise SnapshotError(f"snapshot file missing: {name}")
        if hashlib.sha256(path.read_bytes()).hexdigest() != expected:
            raise SnapshotError(f"checksum mismatch: {name}")
    return Snapshot(
        root=root,
        events=json.loads((root / "events.json").read_text()),
        origin=origin,
        manifest_hash=hashlib.sha256(raw).hexdigest(),
    )


def _station_coordinates(meta, origin) -> tuple[tuple[float, float], float]:
    xy = aeqd_forward(meta["lat"], meta["lon"], origin["lat"], origin["lon"])
    return xy, meta["elevation_m"] / 1000.0


def _locate_with_rejection(xy, h_km, times) -> tuple[Solution, list[int], list[int]]:
    """Locate, dropping the worst pick while it exceeds 1.5 s and at least 5 picks remain."""
    xy, h_km, times = np.asarray(xy), np.asarray(h_km), np.asarray(times)
    kept, rejected = list(range(len(times))), []
    while True:
        sol = locate(xy[kept], h_km[kept], times[kept])
        r = times[kept] - (sol.t0 + travel_time(sol.x_km, sol.y_km, xy[kept], h_km[kept]))
        worst = int(np.argmax(np.abs(r)))
        if abs(r[worst]) <= _MAX_RESIDUAL_S or len(kept) < _MIN_PICKS_TO_REJECT:
            return sol, kept, rejected
        rejected.append(kept.pop(worst))


def _false_trigger_count(episodes, start_s, fs) -> int:
    first = (_FALSE_TRIGGER_START_S) * fs
    last = (_FALSE_TRIGGER_END_S - start_s) * fs
    return sum(first <= e.on_idx <= last for e in episodes)


def locate_event(snapshot: Snapshot, event_id: str, on_realdata: float) -> EventResult:
    """Run the chain on one event. Raises KeyError for an unknown id."""
    event = next((e for e in snapshot.events if e["id"] == event_id), None)
    if event is None:
        raise KeyError(event_id)
    names, xy, h_km, times, skipped, false_triggers = [], [], [], [], {}, {}
    with np.load(snapshot.root / "waveforms" / f"{event_id}.npz") as waveforms:
        for meta in event["stations"]:
            name, fs = meta["station"], float(meta["sampling_rate"])
            start_s = float(waveforms[f"{name}__start"])
            try:
                x = preprocess_real(waveforms[name], fs)
                result = pick_trace(x, fs, on_realdata, blank_s=BLANK_S)
            except SignalError as exc:
                skipped[name] = str(exc)
                continue
            if result.pick_idx is None:
                skipped[name] = "no detection"
                continue
            position, elevation = _station_coordinates(meta, snapshot.origin)
            names.append(name)
            xy.append(position)
            h_km.append(elevation)
            times.append(start_s + result.pick_idx / fs)
            false_triggers[name] = _false_trigger_count(result.episodes, start_s, fs)
    if len(times) < 4:
        return EventResult(
            event_id,
            False,
            reason=f"need at least 4 picks, got {len(times)}",
            skipped=skipped,
            false_triggers=false_triggers,
        )
    try:
        sol, kept, rejected = _locate_with_rejection(xy, h_km, times)
    except LocationError as exc:
        return EventResult(
            event_id, False, reason=str(exc), skipped=skipped, false_triggers=false_triggers
        )
    lat, lon = aeqd_inverse(sol.x_km, sol.y_km, snapshot.origin["lat"], snapshot.origin["lon"])
    tt = {
        i: float(travel_time(sol.x_km, sol.y_km, np.array([xy[i]]), np.array([h_km[i]]))[0])
        for i in rejected
    }
    return EventResult(
        event_id,
        True,
        lat=lat,
        lon=lon,
        t0=sol.t0,
        ellipse=sol.ellipse,
        rms_s=sol.rms_s,
        used=[names[i] for i in kept],
        rejected={names[i]: times[i] - sol.t0 - tt[i] for i in rejected},
        skipped=skipped,
        mislocation_km=haversine_km(lat, lon, event["lat"], event["lon"]),
        dt0_s=sol.t0,  # the catalog origin time is the reference, so this is the difference
        false_triggers={names[i]: false_triggers[names[i]] for i in kept},
    )


def _csv_row(r: EventResult) -> dict:
    return {
        "event_id": r.event_id,
        "located": r.located,
        "reason": r.reason,
        "lat": r.lat,
        "lon": r.lon,
        "t0_s": r.t0,
        "a_km": r.ellipse.a_km if r.ellipse else None,
        "b_km": r.ellipse.b_km if r.ellipse else None,
        "azimuth_deg": r.ellipse.azimuth_deg if r.ellipse else None,
        "rms_s": r.rms_s,
        "used": " ".join(r.used),
        "rejected": json.dumps(r.rejected),
        "skipped": json.dumps(r.skipped),
        "mislocation_km": r.mislocation_km,
        "dt0_s": r.dt0_s,
        "false_triggers": json.dumps(r.false_triggers),
    }


def relocate_all(root, artifacts, out_csv) -> list[EventResult]:
    snapshot = load_snapshot(root)
    on = json.loads((Path(artifacts) / "detector.json").read_text())["on_realdata"]
    results = [locate_event(snapshot, e["id"], on) for e in snapshot.events]
    out = Path(out_csv)
    out.parent.mkdir(parents=True, exist_ok=True)
    with out.open("w", newline="") as f:
        writer = csv.DictWriter(f, CSV_COLUMNS)
        writer.writeheader()
        writer.writerows(_csv_row(r) for r in results)
    return results


def write_gates(results, snapshot: Snapshot, path) -> dict:
    located = [r for r in results if r.located]
    if not located:
        raise SnapshotError("no event located: gates cannot be derived")
    gates = {
        "max_median_mislocation_km": _GATE_HEADROOM
        * float(np.median([r.mislocation_km for r in located])),
        "max_rms_s": _GATE_HEADROOM * max(r.rms_s for r in located),
        "min_located_fraction": len(located) / len(results),
        "rationale": "Derived from the first honest run: 1.5x the measured median mislocation "
        "and max RMS, and the measured located fraction. Change only with a new snapshot.",
        "snapshot_hash": snapshot.manifest_hash,
    }
    Path(path).write_text(json.dumps(gates, indent=2, sort_keys=True) + "\n")
    return gates


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--snapshot", default="data/real")
    parser.add_argument("--artifacts", default="artifacts")
    parser.add_argument("--out", default="reports/relocation.csv")
    parser.add_argument("--write-gates")
    args = parser.parse_args(argv)
    results = relocate_all(args.snapshot, args.artifacts, args.out)
    for r in results:
        status = f"{r.mislocation_km:.1f} km" if r.located else f"not located: {r.reason}"
        print(f"{r.event_id}: {status}")
    if args.write_gates:
        write_gates(results, load_snapshot(args.snapshot), args.write_gates)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
