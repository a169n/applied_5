"""One-layer travel-time model shared by the generator and the locator."""

import json
from dataclasses import dataclass
from pathlib import Path

import numpy as np

from quakeloc.paths import config_dir

VP_KM_S = 6.0
DEPTH_KM = 10.0


@dataclass(frozen=True)
class Network:
    names: list[str]
    xy: np.ndarray  # (n, 2), km
    h_km: np.ndarray  # (n,), station elevation above sea level, km


def travel_time(x_km, y_km, sta_xy, h_km, z_km=DEPTH_KM, vp=VP_KM_S):
    """P travel time from a source at (x, y, depth z) to each station."""
    dx = sta_xy[:, 0] - x_km
    dy = sta_xy[:, 1] - y_km
    dz = z_km + h_km
    return np.sqrt(dx**2 + dy**2 + dz**2) / vp


def load_network(path: Path | None = None) -> Network:
    path = path or config_dir() / "network.json"
    stations = json.loads(Path(path).read_text())["stations"]
    return Network(
        names=[s["name"] for s in stations],
        xy=np.array([[s["x_km"], s["y_km"]] for s in stations], dtype=float),
        h_km=np.array([s["elevation_km"] for s in stations], dtype=float),
    )
