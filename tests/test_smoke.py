import pytest
from fastapi.testclient import TestClient
from test_api import MINI

from quakeloc.api import create_app
from quakeloc.smoke import check, wait_ready


def _get(client):
    def get(path):
        r = client.get(path)
        is_json = r.headers["content-type"].startswith("application/json")
        return r.status_code, r.json() if is_json else r.text

    return get


@pytest.fixture
def client(tiny_artifacts, tmp_path, monkeypatch):
    monkeypatch.setenv("GIT_SHA", "abc")
    return TestClient(create_app(artifacts=tiny_artifacts, snapshot=tmp_path))


def test_smoke_passes_against_testclient(client):
    assert check(_get(client), expected_sha="abc") == []


def test_smoke_fails_on_wrong_sha(client):
    failures = check(_get(client), expected_sha="other")
    assert len(failures) == 1 and "other" in failures[0]


def test_smoke_fails_when_the_web_client_is_missing(client):
    real = _get(client)

    def get(path):
        return (404, None) if path == "/" else real(path)

    assert check(get) == ["/ returned 404, not the web client"]


def test_smoke_skips_events_without_snapshot(client, capsys):
    check(_get(client))
    assert "SKIP: no snapshot" in capsys.readouterr().out


def test_smoke_locates_a_fixture_event(tiny_artifacts):
    c = TestClient(create_app(artifacts=tiny_artifacts, snapshot=MINI))
    assert check(_get(c)) == []


def test_smoke_fails_when_no_event_locates(client):
    def get(path):
        if path == "/events":
            return 200, [{"id": "a"}]
        if path == "/events/a/locate":
            return 422, {"detail": "nope"}
        return _get(client)(path)

    assert any("no event" in f for f in check(get))


def test_wait_ready_times_out_on_unreachable():
    def get(path):
        raise OSError("refused")

    assert wait_ready(get, timeout_s=0.01, interval_s=0.001) is False


def test_wait_ready_succeeds(client):
    assert wait_ready(_get(client), timeout_s=1) is True
