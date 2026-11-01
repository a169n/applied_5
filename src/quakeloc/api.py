"""quakeloc HTTP service."""

import hashlib
import json
import os
from dataclasses import asdict
from pathlib import Path

import numpy as np
from fastapi import FastAPI, HTTPException, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import FileResponse, JSONResponse

import quakeloc
from quakeloc.detect import SignalError
from quakeloc.locate import LocationError, locate
from quakeloc.model import load_network
from quakeloc.paths import artifacts_dir, config_dir, snapshot_dir
from quakeloc.pipeline import locate_synth, pick_trace
from quakeloc.realdata import SnapshotError, has_snapshot, load_snapshot, locate_event
from quakeloc.schemas import LocateRequest, PickRequest, SimulateRequest
from quakeloc.synth import FS_HZ, event

_MAX_PREVIEW_SAMPLES = 500
_DEMO = {"x_km": 50.0, "y_km": 50.0, "seed": 42, "min_snr": 10.0}
_SELF_TEST = {"x_km": 48.0, "y_km": 52.0, "seed": 1, "min_snr": 12.0}
_SELF_TEST_TOLERANCE_KM = 0.5


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _load_detector(artifacts: Path) -> dict:
    """Load detector.json, verified against manifest.json. Raises ValueError with the reason."""
    try:
        manifest = json.loads((artifacts / "manifest.json").read_text())
        path = artifacts / "detector.json"
        if _sha256(path) != manifest["outputs"]["detector.json"]:
            raise ValueError("detector.json hash does not match manifest.json")
        return json.loads(path.read_text())
    except (OSError, KeyError, json.JSONDecodeError) as exc:
        raise ValueError(f"calibration artifacts unavailable: {exc}") from exc


def _location_error_km(result, x, y) -> float:
    return float(np.hypot(result.solution.x_km - x, result.solution.y_km - y))


def _self_test(detector: dict, network) -> None:
    case = _SELF_TEST
    ev = event(case["x_km"], case["y_km"], case["seed"], case["min_snr"], network=network)
    try:
        error = _location_error_km(locate_synth(ev, detector["on_raw"]), case["x_km"], case["y_km"])
    except (LocationError, SignalError) as exc:
        raise ValueError(f"self-test failed: {exc}") from exc
    if error > _SELF_TEST_TOLERANCE_KM:
        raise ValueError(f"self-test error {error:.3f} km exceeds {_SELF_TEST_TOLERANCE_KM} km")


def create_app(artifacts=None, snapshot=None, config=None) -> FastAPI:
    artifacts = Path(artifacts) if artifacts is not None else artifacts_dir()
    snapshot = Path(snapshot) if snapshot is not None else snapshot_dir()
    config = Path(config) if config is not None else config_dir()
    app = FastAPI(title="quakeloc", version=quakeloc.__version__)

    @app.exception_handler(RequestValidationError)
    async def validation_error(_: Request, exc: RequestValidationError):
        # The default handler echoes the input: non-finite values in it crash JSON rendering,
        # and a 200 k sample payload would come straight back.
        errors = [{"loc": list(e["loc"]), "msg": e["msg"]} for e in exc.errors()]
        return JSONResponse(status_code=422, content={"detail": errors})

    def network():
        return load_network(config / "network.json")

    def readiness() -> tuple[dict | None, str]:
        """Detector and failure reason; computed once per process (the inputs are immutable)."""
        if not hasattr(app.state, "readiness"):
            try:
                detector = _load_detector(artifacts)
                _self_test(detector, network())
                app.state.readiness = (detector, "")
            except ValueError as exc:
                app.state.readiness = (None, str(exc))
        return app.state.readiness

    def require_detector() -> dict:
        detector, reason = readiness()
        if detector is None:
            raise HTTPException(503, reason)
        return detector

    def require_snapshot():
        try:
            return load_snapshot(snapshot)
        except SnapshotError as exc:
            raise HTTPException(503, f"snapshot failed verification: {exc}") from exc

    @app.get("/", include_in_schema=False)
    def web_client():
        return FileResponse(Path(__file__).with_name("index.html"))

    @app.get("/health")
    def health():
        return {"status": "ok"}

    @app.get("/ready")
    def ready():
        require_detector()
        return {"status": "ready"}

    @app.get("/version")
    def version():
        detector_path = artifacts / "detector.json"
        manifest_path = snapshot / "MANIFEST.json"
        return {
            "git_sha": os.environ.get("GIT_SHA", "unknown"),
            "build_number": os.environ.get("BUILD_NUMBER", "unknown"),
            "package": quakeloc.__version__,
            "numpy": np.__version__,
            "artifact_hash": _sha256(detector_path) if detector_path.exists() else None,
            "snapshot_hash": _sha256(manifest_path) if manifest_path.exists() else None,
        }

    @app.post("/simulate")
    def simulate(req: SimulateRequest):
        try:
            ev = event(req.x_km, req.y_km, req.seed, req.min_snr, network=network())
        except ValueError as exc:
            raise HTTPException(422, str(exc)) from exc
        stations = []
        for name, x in ev.traces.items():
            step = max(1, len(x) // _MAX_PREVIEW_SAMPLES)
            stations.append(
                {
                    "station": name,
                    "arrival_s": ev.arrivals_s[name],
                    "snr": ev.snrs[name],
                    "fs_hz": FS_HZ / step,
                    "samples": np.round(x[::step], 3).tolist(),
                }
            )
        return {"t0_s": ev.t0_s, "stations": stations}

    @app.post("/pick")
    def pick(req: PickRequest):
        on = require_detector()["on_raw"]
        try:
            # Raw counts carry a large offset, which would swamp the energy ratio.
            samples = np.array(req.samples)
            result = pick_trace(samples - samples.mean(), req.fs_hz, on)
        except SignalError as exc:
            raise HTTPException(422, str(exc)) from exc
        return {
            "episodes": [asdict(e) for e in result.episodes],
            "trigger_idx": result.trigger_idx,
            "pick_idx": result.pick_idx,
            "pick_time_s": None if result.pick_idx is None else result.pick_idx / req.fs_hz,
        }

    @app.post("/locate")
    def locate_picks(req: LocateRequest):
        net = network()
        index = {name: i for i, name in enumerate(net.names)}
        seen = set()
        for p in req.picks:
            if p.station not in index:
                raise HTTPException(422, f"unknown station: {p.station}")
            if p.station in seen:
                raise HTTPException(422, f"duplicate pick for station: {p.station}")
            seen.add(p.station)
        keep = [index[p.station] for p in req.picks]
        try:
            sol = locate(net.xy[keep], net.h_km[keep], [p.t for p in req.picks], req.sigma_s)
        except LocationError as exc:
            raise HTTPException(422, str(exc)) from exc
        return asdict(sol)

    @app.get("/demo")
    def demo():
        on = require_detector()["on_raw"]
        c = _DEMO
        result = locate_synth(event(c["x_km"], c["y_km"], c["seed"], c["min_snr"], network()), on)
        return {
            "truth": {"x_km": c["x_km"], "y_km": c["y_km"], "t0": 20.0},
            "estimate": asdict(result.solution),
            "error_km": _location_error_km(result, c["x_km"], c["y_km"]),
            "picks": result.picks,
        }

    @app.get("/events")
    def events():
        if not has_snapshot(snapshot):
            return []
        return [
            {k: e[k] for k in ("id", "time", "magnitude", "lat", "lon", "depth_km")}
            for e in require_snapshot().events
        ]

    @app.get("/events/{event_id}/locate")
    def locate_real(event_id: str):
        if not has_snapshot(snapshot):
            raise HTTPException(404, "no snapshot in this image")
        snap = require_snapshot()
        try:
            r = locate_event(snap, event_id, require_detector()["on_realdata"])
        except KeyError as exc:
            raise HTTPException(404, f"unknown event: {event_id}") from exc
        if not r.located:
            raise HTTPException(422, r.reason)
        usgs = next(e for e in snap.events if e["id"] == event_id)
        return {
            "id": event_id,
            "located": {"lat": r.lat, "lon": r.lon, "t0_s": r.t0, "rms_s": r.rms_s},
            "ellipse": asdict(r.ellipse),
            "usgs": {k: usgs[k] for k in ("lat", "lon", "depth_km", "magnitude", "time")},
            "mislocation_km": r.mislocation_km,
            "used": r.used,
            "rejected": r.rejected,
            "skipped": r.skipped,
        }

    return app


app = create_app()
