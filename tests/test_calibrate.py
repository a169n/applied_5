import json

import quakeloc.calibrate as cal
from quakeloc.locate import LocationError

TINY = dict(n_traces=12, n_noise=12, n_events=3)


def test_writes_all_metrics(tiny_artifacts):
    d = json.loads((tiny_artifacts / "detector.json").read_text())
    for key in (
        "on_raw",
        "on_realdata",
        "precision",
        "recall",
        "recall_snr5",
        "pick_err_median_s",
        "pick_err_mad_s",
        "mean_loc_err_km",
        "location_errors",
    ):
        assert key in d
    assert d["on_raw"] > 1.5 and d["on_realdata"] > 1.5


def test_calibrate_deterministic(tmp_path):
    a, b = tmp_path / "a", tmp_path / "b"
    cal.calibrate(42, a, **TINY)
    cal.calibrate(42, b, **TINY)
    for name in ("detector.json", "manifest.json"):
        assert (a / name).read_bytes() == (b / name).read_bytes()


def test_different_seed_changes_result(tmp_path):
    a, b = tmp_path / "a", tmp_path / "b"
    cal.calibrate(42, a, **TINY)
    cal.calibrate(43, b, **TINY)
    assert (a / "detector.json").read_bytes() != (b / "detector.json").read_bytes()


def test_manifest_has_hashes_no_git_sha(tiny_artifacts):
    text = (tiny_artifacts / "manifest.json").read_text()
    m = json.loads(text)
    assert m["seed"] == 42 and m["numpy"]
    assert "src/quakeloc/locate.py" in m["inputs"] and "config/network.json" in m["inputs"]
    assert set(m["outputs"]) == {"detector.json"}
    assert "git" not in text.lower()


def test_location_error_counted_not_fatal(tmp_path, monkeypatch):
    real = cal.locate_synth
    calls = []

    def flaky(ev, on):
        calls.append(1)
        if len(calls) == 1:
            raise LocationError("forced")
        return real(ev, on)

    monkeypatch.setattr(cal, "locate_synth", flaky)
    assert cal.calibrate(42, tmp_path, **TINY)["location_errors"] == 1


def test_cli(tmp_path):
    assert cal.main(["--seed", "42", "--out", str(tmp_path), "--tiny"]) == 0
    assert (tmp_path / "detector.json").exists()
