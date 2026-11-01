"""Selection logic of the fetcher. ObsPy is not installed in the test image, on purpose."""

import subprocess
import sys

import pytest

from quakeloc.data.fetch import azimuth_deg, azimuthal_gap, rank_events


def test_gap_uniform():
    assert azimuthal_gap([0, 90, 180, 270]) == 90


def test_gap_wraps():
    assert azimuthal_gap([350, 10]) == 340


def test_gap_unsorted():
    assert azimuthal_gap([200, 10, 100]) == 170


def test_azimuth_cardinal():
    assert azimuth_deg(42.0, 74.0, 43.0, 74.0) == pytest.approx(0.0, abs=1e-6)
    assert azimuth_deg(42.0, 74.0, 42.0, 75.0) == pytest.approx(90.0, abs=1.0)


def test_rank_order():
    def c(id_, n, gap, mag):
        return {"id": id_, "n_stations": n, "gap_deg": gap, "magnitude": mag}

    candidates = [
        c("e", 6, 100, 5.0),
        c("d", 7, 150, 4.0),
        c("c", 7, 100, 4.0),
        c("b", 7, 100, 5.0),
        c("a", 7, 100, 5.0),
    ]
    assert [x["id"] for x in rank_events(candidates, 4)] == ["a", "b", "c", "d"]


def test_module_does_not_import_obspy_at_import_time():
    code = "import sys, quakeloc.data.fetch; assert 'obspy' not in sys.modules"
    subprocess.run([sys.executable, "-c", code], check=True)
