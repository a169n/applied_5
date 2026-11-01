import csv

from quakeloc.experiment import main, sweep


def test_sweep_tiny(tmp_path):
    out = tmp_path / "snr_sweep.csv"
    rows = sweep(seeds=[1, 2], snrs=[5.0, 20.0], on=2.05, out_csv=out)
    assert [r["snr"] for r in rows] == [5.0, 20.0]
    with out.open() as f:
        reader = csv.DictReader(f)
        assert reader.fieldnames == ["snr", "recall", "pick_err_s", "loc_err_km", "coverage"]
        assert len(list(reader)) == 2
    assert rows[1]["recall"] == 1.0 and rows[1]["loc_err_km"] < 1.0


def test_cli_reads_threshold_from_artifacts(tiny_artifacts, tmp_path):
    out = tmp_path / "s.csv"
    assert main(["--artifacts", str(tiny_artifacts), "--out", str(out), "--tiny"]) == 0
    assert out.exists()
