"""Real-data code against a labelled synthetic snapshot, so it runs in the fast suite."""

import csv
import json
import shutil
from pathlib import Path

import numpy as np
import pytest

from quakeloc.geo import aeqd_forward
from quakeloc.model import travel_time
from quakeloc.realdata import (
    SnapshotError,
    _locate_with_rejection,
    has_snapshot,
    load_snapshot,
    locate_event,
    main,
    relocate_all,
    write_gates,
)

MINI = Path(__file__).parent / "fixtures" / "mini_snapshot"
ON = 4.0


@pytest.fixture(scope="module")
def snapshot():
    return load_snapshot(MINI)


@pytest.fixture(scope="module")
def event1(snapshot):
    return locate_event(snapshot, "synth0001", ON)


def test_has_snapshot(tmp_path):
    assert has_snapshot(MINI) and not has_snapshot(tmp_path)


def test_tampered_file_raises(tmp_path):
    root = tmp_path / "snap"
    shutil.copytree(MINI, root)
    victim = root / "waveforms" / "synth0001.npz"
    data = bytearray(victim.read_bytes())
    data[100] ^= 0xFF
    victim.write_bytes(bytes(data))
    with pytest.raises(SnapshotError, match="synth0001.npz"):
        load_snapshot(root)


def test_missing_file_raises(tmp_path):
    root = tmp_path / "snap"
    shutil.copytree(MINI, root)
    (root / "events.json").unlink()
    with pytest.raises(SnapshotError, match="events.json"):
        load_snapshot(root)


def test_unknown_event_raises_keyerror(snapshot):
    with pytest.raises(KeyError):
        locate_event(snapshot, "nope", ON)


def test_flat_station_skipped_with_reason(event1):
    assert event1.located and "FLT" in event1.skipped and "flat" in event1.skipped["FLT"]


def test_nan_gap_station_skipped(event1):
    assert "NAN" in event1.skipped and "finite" in event1.skipped["NAN"]


def test_mixed_sampling_rate_uses_station_fs(event1):
    # EEE is the 100 Hz station; the rest are 40 Hz. Using one rate would shift it by seconds.
    assert "EEE" in event1.used and event1.rejected == {}
    assert event1.rms_s < 0.2


def test_too_few_picks_not_located(snapshot):
    r = locate_event(snapshot, "synth0002", ON)
    assert not r.located and "4 picks" in r.reason and r.mislocation_km is None


def test_mislocation_small_on_fixture(event1):
    assert event1.mislocation_km < 5.0
    assert abs(event1.dt0_s) < 1.0  # known positive bias from the causal filter is ~0.1 s


def test_false_triggers_reported_per_trace(event1):
    assert set(event1.false_triggers) == set(event1.used)
    assert all(v >= 0 for v in event1.false_triggers.values())


def _picks(n, outlier=None):
    angles = np.linspace(0, 2 * np.pi, n, endpoint=False)
    xy = np.column_stack([80 * np.cos(angles), 80 * np.sin(angles)])
    h = np.zeros(n)
    t = 20 + travel_time(5, 5, xy, h)
    if outlier is not None:
        t[outlier] += 5.0
    return xy, h, t


def test_outlier_rejected_and_relocated():
    xy, h, t = _picks(8, outlier=3)
    sol, kept, rejected = _locate_with_rejection(xy, h, t)
    assert rejected == [3] and len(kept) == 7
    assert np.hypot(sol.x_km - 5, sol.y_km - 5) < 1e-3


def test_rejection_stops_at_four_picks():
    xy, h, t = _picks(4, outlier=1)
    # Four picks may fit with large residuals, but none can be dropped below the minimum.
    _, kept, rejected = _locate_with_rejection(xy, h, t)
    assert rejected == [] and len(kept) == 4


def test_elevation_converted_once(snapshot):
    from quakeloc.realdata import _station_coordinates

    meta = snapshot.events[0]["stations"][0]
    xy, h_km = _station_coordinates(meta, snapshot.origin)
    assert h_km == pytest.approx(meta["elevation_m"] / 1000.0)
    assert xy == pytest.approx(
        aeqd_forward(meta["lat"], meta["lon"], snapshot.origin["lat"], snapshot.origin["lon"])
    )


def test_relocate_all_continues_and_writes_csv(tiny_artifacts, tmp_path):
    out = tmp_path / "relocation.csv"
    results = relocate_all(MINI, tiny_artifacts, out)
    assert [r.located for r in results] == [True, False]
    with out.open() as f:
        rows = list(csv.DictReader(f))
    assert len(rows) == 2
    for column in (
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
    ):
        assert column in rows[0]


def test_write_gates_formula(snapshot, tiny_artifacts, tmp_path):
    results = relocate_all(MINI, tiny_artifacts, tmp_path / "r.csv")
    path = tmp_path / "gates.json"
    write_gates(results, snapshot, path)
    g = json.loads(path.read_text())
    located = [r for r in results if r.located]
    assert g["max_median_mislocation_km"] == pytest.approx(
        1.5 * np.median([r.mislocation_km for r in located])
    )
    assert g["max_rms_s"] == pytest.approx(1.5 * max(r.rms_s for r in located))
    assert g["min_located_fraction"] == pytest.approx(0.5)
    assert g["rationale"] and g["snapshot_hash"] == snapshot.manifest_hash


def test_cli(tiny_artifacts, tmp_path):
    out, gates = tmp_path / "r.csv", tmp_path / "g.json"
    argv = ["--snapshot", str(MINI), "--artifacts", str(tiny_artifacts), "--out", str(out)]
    assert main([*argv, "--write-gates", str(gates)]) == 0
    assert out.exists() and gates.exists()


def test_corrupt_manifest_is_a_snapshot_error(tmp_path):
    root = tmp_path / "snap"
    shutil.copytree(MINI, root)
    (root / "MANIFEST.json").write_text("not json")
    with pytest.raises(SnapshotError, match="MANIFEST"):
        load_snapshot(root)
