"""Gates on the committed real KNET snapshot. Requires artifacts/ from a calibration run."""

import json

import numpy as np
import pytest

from quakeloc.paths import artifacts_dir, config_dir, snapshot_dir
from quakeloc.realdata import has_snapshot, load_snapshot, relocate_all

pytestmark = [
    pytest.mark.realdata,
    pytest.mark.skipif(not has_snapshot(snapshot_dir()), reason="no real snapshot committed"),
]


@pytest.fixture(scope="module")
def results(tmp_path_factory):
    out = tmp_path_factory.mktemp("relocation") / "relocation.csv"
    return relocate_all(snapshot_dir(), artifacts_dir(), out)


@pytest.fixture(scope="module")
def gates():
    return json.loads((config_dir() / "realdata_gates.json").read_text())  # missing file fails


def test_every_event_processed(results):
    assert len(results) == len(load_snapshot(snapshot_dir()).events)


def test_gates_match_snapshot(gates):
    assert gates["snapshot_hash"] == load_snapshot(snapshot_dir()).manifest_hash


def test_median_mislocation_within_gate(results, gates):
    located = [r.mislocation_km for r in results if r.located]
    assert np.median(located) <= gates["max_median_mislocation_km"]


def test_max_rms_within_gate(results, gates):
    assert max(r.rms_s for r in results if r.located) <= gates["max_rms_s"]


def test_located_fraction_within_gate(results, gates):
    assert np.mean([r.located for r in results]) >= gates["min_located_fraction"]
