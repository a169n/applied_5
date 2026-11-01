import json
import shutil
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from quakeloc.api import create_app
from quakeloc.model import load_network, travel_time

MINI = Path(__file__).parent / "fixtures" / "mini_snapshot"


@pytest.fixture
def client(tiny_artifacts, tmp_path):
    return TestClient(create_app(artifacts=tiny_artifacts, snapshot=tmp_path))


@pytest.fixture
def fixture_client(tiny_artifacts):
    return TestClient(create_app(artifacts=tiny_artifacts, snapshot=MINI))


def _good_picks(xy=(50, 50)):
    net = load_network()
    times = 20 + travel_time(xy[0], xy[1], net.xy, net.h_km)
    return [{"station": n, "t": float(t)} for n, t in zip(net.names, times, strict=True)]


def test_root_serves_the_web_client(client):
    r = client.get("/")
    assert r.status_code == 200
    assert r.headers["content-type"].startswith("text/html")
    assert "/events" in r.text


def test_health_and_ready_ok(client):
    assert client.get("/health").status_code == 200
    assert client.get("/ready").status_code == 200


def test_ready_503_on_tampered_artifact(tiny_artifacts, tmp_path):
    art = tmp_path / "art"
    shutil.copytree(tiny_artifacts, art)
    d = json.loads((art / "detector.json").read_text())
    d["on_raw"] = 99.0
    (art / "detector.json").write_text(json.dumps(d))
    c = TestClient(create_app(artifacts=art, snapshot=tmp_path))
    r = c.get("/ready")
    assert r.status_code == 503 and "hash" in r.json()["detail"]


def test_ready_503_on_missing_artifact_but_health_200(tmp_path):
    c = TestClient(create_app(artifacts=tmp_path / "none", snapshot=tmp_path))
    assert c.get("/health").status_code == 200
    assert c.get("/ready").status_code == 503
    assert c.get("/demo").status_code == 503


def test_version_fields(client, monkeypatch):
    monkeypatch.setenv("GIT_SHA", "abc123")
    monkeypatch.setenv("BUILD_NUMBER", "7")
    v = client.get("/version").json()
    assert v["git_sha"] == "abc123" and v["build_number"] == "7"
    assert v["package"] == "1.0.0" and v["numpy"] and v["artifact_hash"]
    assert v["snapshot_hash"] is None


def test_version_reports_snapshot_hash(fixture_client):
    assert fixture_client.get("/version").json()["snapshot_hash"]


def test_demo_error_under_1km(client):
    r = client.get("/demo").json()
    assert r["error_km"] < 1.0 and r["truth"] and r["estimate"]


def test_simulate_returns_capped_event(client):
    r = client.post("/simulate", json={"seed": 1, "x_km": 50, "y_km": 50, "min_snr": 10})
    assert r.status_code == 200
    stations = r.json()["stations"]
    assert len(stations) == 8
    assert all(len(s["samples"]) <= 500 for s in stations)


@pytest.mark.parametrize(
    "body",
    [
        {"seed": 1, "x_km": 5000, "y_km": 0, "min_snr": 10},
        {"seed": 1, "x_km": 50, "y_km": 50, "min_snr": 0},
        {"seed": -1, "x_km": 50, "y_km": 50, "min_snr": 10},
        {"seed": 1, "x_km": 1e308, "y_km": 50, "min_snr": 10},
    ],
)
def test_simulate_out_of_range_422(client, body):
    assert client.post("/simulate", json=body).status_code == 422


def test_pick_finds_onset(client):
    from quakeloc.synth import trace

    r = client.post("/pick", json={"samples": trace(20, 30.0, 1).tolist(), "fs_hz": 100})
    assert r.status_code == 200
    assert abs(r.json()["pick_time_s"] - 30.0) < 0.1 and r.json()["episodes"]


def test_pick_noise_is_no_detection(client):
    from quakeloc.synth import noise

    r = client.post("/pick", json={"samples": noise(1).tolist(), "fs_hz": 100}).json()
    assert "pick_idx" in r


@pytest.mark.parametrize(
    "raw",
    [
        '{"samples": [1.0, NaN, 2.0], "fs_hz": 100}',
        '{"samples": [1.0, Infinity, 2.0], "fs_hz": 100}',
        '{"samples": [1.0, 2.0, 3.0], "fs_hz": 0}',
        '{"samples": [1.0, 2.0, 3.0], "fs_hz": -5}',
        '{"samples": [1.0, 2.0, 3.0], "fs_hz": 100}',
        '{"samples": [1.0, 2.0, 3.0], "fs_hz": 0.001}',
        '{"samples": ' + json.dumps([0.0] * 6000) + ', "fs_hz": 100}',
        '{"samples": ' + json.dumps([0.0] * 200001) + ', "fs_hz": 100}',
    ],
    ids=["nan", "inf", "fs0", "fsneg", "short", "fstiny", "flat", "toolong"],
)
def test_pick_rejects_bad_input_422(client, raw):
    r = client.post("/pick", content=raw, headers={"content-type": "application/json"})
    assert r.status_code == 422


def test_validation_error_does_not_echo_payload(client):
    raw = '{"samples": [1.0, NaN], "fs_hz": 100}'
    r = client.post("/pick", content=raw, headers={"content-type": "application/json"})
    assert "input" not in r.text


def test_locate_ok(client):
    r = client.post("/locate", json={"picks": _good_picks((40, 60))})
    assert r.status_code == 200
    b = r.json()
    assert b["x_km"] == pytest.approx(40, abs=1e-4) and b["y_km"] == pytest.approx(60, abs=1e-4)
    assert set(b["ellipse"]) == {"a_km", "b_km", "azimuth_deg"}
    assert {"t0", "rms_s", "iterations", "cond"} <= set(b)


def test_locate_duplicate_station_422(client):
    picks = _good_picks()
    picks[1]["station"] = picks[0]["station"]
    r = client.post("/locate", json={"picks": picks})
    assert r.status_code == 422 and "ST01" in r.text


def test_locate_unknown_station_422(client):
    picks = _good_picks()
    picks[0]["station"] = "XXXX"
    r = client.post("/locate", json={"picks": picks})
    assert r.status_code == 422 and "XXXX" in r.text


def test_locate_bad_sigma_422(client):
    assert client.post("/locate", json={"picks": _good_picks(), "sigma_s": 0}).status_code == 422


def test_locate_three_picks_422(client):
    r = client.post("/locate", json={"picks": _good_picks()[:3]})
    assert r.status_code == 422 and "4 picks" in r.text


def test_locate_non_finite_time_422(client):
    picks = json.dumps({"picks": _good_picks()}).replace(str(_good_picks()[0]["t"]), "NaN", 1)
    r = client.post("/locate", content=picks, headers={"content-type": "application/json"})
    assert r.status_code == 422


def test_events_empty_and_404_without_snapshot(client):
    assert client.get("/events").json() == []
    assert client.get("/events/any/locate").status_code == 404


def test_events_lists_fixture(fixture_client):
    events = fixture_client.get("/events").json()
    assert {e["id"] for e in events} == {"synth0001", "synth0002"}
    assert {"id", "time", "magnitude", "lat", "lon"} <= set(events[0])


def test_unknown_event_404(fixture_client):
    assert fixture_client.get("/events/nope/locate").status_code == 404


def test_fixture_event_locates(fixture_client):
    r = fixture_client.get("/events/synth0001/locate")
    assert r.status_code == 200
    b = r.json()
    assert b["mislocation_km"] < 5 and b["usgs"]["lat"] and b["located"]["lat"]


def test_too_few_picks_event_422(fixture_client):
    r = fixture_client.get("/events/synth0002/locate")
    assert r.status_code == 422 and "4 picks" in r.text


def test_tampered_snapshot_503_ready_unaffected(tiny_artifacts, tmp_path):
    root = tmp_path / "snap"
    shutil.copytree(MINI, root)
    c = TestClient(create_app(artifacts=tiny_artifacts, snapshot=root))
    assert c.get("/events/synth0001/locate").status_code == 200
    victim = root / "waveforms" / "synth0001.npz"
    data = bytearray(victim.read_bytes())
    data[100] ^= 0xFF
    victim.write_bytes(bytes(data))
    r = c.get("/events/synth0001/locate")
    assert r.status_code == 503 and "checksum" in r.text
    assert c.get("/ready").status_code == 200


@pytest.mark.parametrize("sigma", [1e154, 1e308])
def test_locate_huge_sigma_422(client, sigma):
    assert (
        client.post("/locate", json={"picks": _good_picks(), "sigma_s": sigma}).status_code == 422
    )


def test_locate_huge_times_422(client):
    picks = [{"station": p["station"], "t": 1e154} for p in _good_picks()]
    assert client.post("/locate", json={"picks": picks}).status_code == 422


@pytest.mark.parametrize(
    "body", ["not json", '{"origin": {}}', "[]"], ids=["text", "nofiles", "list"]
)
def test_corrupt_manifest_503(tiny_artifacts, tmp_path, body):
    root = tmp_path / "snap"
    shutil.copytree(MINI, root)
    (root / "MANIFEST.json").write_text(body)
    c = TestClient(create_app(artifacts=tiny_artifacts, snapshot=root))
    assert c.get("/events").status_code == 503
    r = c.get("/events/synth0001/locate")
    assert r.status_code == 503 and "MANIFEST" in r.text
    assert c.get("/ready").status_code == 200


@pytest.mark.parametrize("value", [1e200, 1e160])
@pytest.mark.parametrize("index", [100, 3050, 3100])
def test_pick_overflowing_sample_422(client, value, index):
    from quakeloc.synth import trace

    x = trace(20, 30.0, 1)
    x[index] = value
    assert client.post("/pick", json={"samples": x.tolist(), "fs_hz": 100}).status_code == 422


def test_pick_handles_large_offset(client):
    from quakeloc.synth import trace

    x = trace(20, 30.0, 1) + 1.5e6
    r = client.post("/pick", json={"samples": x.tolist(), "fs_hz": 100}).json()
    assert abs(r["pick_time_s"] - 30.0) < 0.1
