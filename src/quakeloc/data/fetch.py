"""Fetch a real-data snapshot: KNET waveforms with USGS catalog solutions.

The only module that uses the network for data. ObsPy is imported lazily because it is
installed only in the `data` image.
"""

import argparse
import datetime as dt
import hashlib
import json
import math
from pathlib import Path

import numpy as np

from quakeloc.geo import aeqd_forward, haversine_km

_USGS_URL = "https://earthquake.usgs.gov/fdsnws/event/1/query"
_STATION_URL = "https://service.earthscope.org/fdsnws/station/1/query"
_DATASELECT_URL = "https://service.earthscope.org/fdsnws/dataselect/1/query"
_KM_PER_DEG = 111.19
_CITATIONS = [
    "KNET, Kyrgyz Digital Network, FDSN network code KN, doi:10.7914/SN/KN",
    "U.S. Geological Survey, Comprehensive Earthquake Catalog (ComCat)",
]


def azimuth_deg(lat, lon, target_lat, target_lon) -> float:
    """Azimuth from (lat, lon) to the target, clockwise from north, in [0, 360)."""
    x, y = aeqd_forward(target_lat, target_lon, lat, lon)
    return math.degrees(math.atan2(x, y)) % 360.0


def azimuthal_gap(azimuths) -> float:
    a = sorted(float(v) % 360.0 for v in azimuths)
    return max((a[(i + 1) % len(a)] - a[i]) % 360.0 or 360.0 for i in range(len(a)))


def rank_events(candidates, max_events) -> list[dict]:
    """Deterministic: station count desc, azimuthal gap asc, magnitude desc, USGS id asc."""
    ordered = sorted(
        candidates, key=lambda c: (-c["n_stations"], c["gap_deg"], -c["magnitude"], c["id"])
    )
    return ordered[:max_events]


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _channels_at(inventory, when, lat, lon, max_km, channels):
    """Per station, the preferred vertical channel valid at ``when`` within ``max_km``."""
    best = {}
    for net in inventory.select(time=when):
        for sta in net:
            for cha in sta:
                if cha.code not in channels:
                    continue
                if haversine_km(lat, lon, cha.latitude, cha.longitude) > max_km:
                    continue
                rank = (channels.index(cha.code), cha.location_code)
                if sta.code not in best or rank < best[sta.code][0]:
                    best[sta.code] = (rank, net.code, cha)
    return {code: (net_code, cha) for code, (_, net_code, cha) in best.items()}


def _complete_trace(stream, station, expected_s):
    """The station's single contiguous trace covering the window, or None."""
    traces = stream.select(station=station)
    if not len(traces):
        return None
    merged = traces.copy().merge(method=0, fill_value=None)
    if len(merged) != 1:
        return None
    tr = merged[0]
    data = tr.data
    if np.ma.isMaskedArray(data) and np.ma.is_masked(data):
        return None
    if tr.stats.npts < expected_s * tr.stats.sampling_rate - 1:
        return None
    return tr


def _as_counts(data) -> np.ndarray:
    data = np.asarray(data)
    return data.astype(np.int32 if np.issubdtype(data.dtype, np.integer) else np.float32)


def _event_id(event) -> str:
    return event.resource_id.id.split("eventid=")[-1].split("&")[0]


def _process_event(event, inventory, client, cfg):
    origin = event.preferred_origin() or event.origins[0]
    magnitude = event.preferred_magnitude() or event.magnitudes[0]
    channels = _channels_at(
        inventory,
        origin.time,
        origin.latitude,
        origin.longitude,
        cfg["station_radius_km"],
        cfg["channels"],
    )
    if len(channels) < cfg["min_stations"]:
        return None
    t1 = origin.time - cfg["window_before_s"]
    t2 = origin.time + cfg["window_after_s"]
    bulk = [
        (net, code, cha.location_code, cha.code, t1, t2) for code, (net, cha) in channels.items()
    ]
    try:
        stream = client.get_waveforms_bulk(bulk)
    except Exception as exc:  # FDSN clients raise many types; a failed event is simply skipped
        print(f"  skipped {_event_id(event)}: {type(exc).__name__}: {exc}")
        return None
    expected_s = cfg["window_before_s"] + cfg["window_after_s"]
    stations, arrays, azimuths = [], {}, []
    for code, (net, cha) in sorted(channels.items()):
        tr = _complete_trace(stream, code, expected_s)
        if tr is None:
            continue
        stations.append(
            {
                "network": net,
                "station": code,
                "location": cha.location_code,
                "channel": cha.code,
                "sampling_rate": float(tr.stats.sampling_rate),
                "lat": cha.latitude,
                "lon": cha.longitude,
                "elevation_m": cha.elevation,
            }
        )
        arrays[code] = _as_counts(tr.data)
        arrays[f"{code}__start"] = np.array(float(tr.stats.starttime - origin.time))
        azimuths.append(azimuth_deg(origin.latitude, origin.longitude, cha.latitude, cha.longitude))
    if len(stations) < cfg["min_stations"]:
        return None
    gap = azimuthal_gap(azimuths)
    if gap > cfg["max_azimuthal_gap_deg"]:
        return None
    return {
        "id": _event_id(event),
        "n_stations": len(stations),
        "gap_deg": gap,
        "magnitude": float(magnitude.mag),
        "summary": {
            "id": _event_id(event),
            "time": origin.time.isoformat() + "Z",
            "lat": origin.latitude,
            "lon": origin.longitude,
            "depth_km": origin.depth / 1000.0 if origin.depth is not None else None,
            "magnitude": float(magnitude.mag),
            "azimuthal_gap_deg": gap,
            "stations": stations,
        },
        "arrays": arrays,
        "window": (str(t1), str(t2)),
    }


def _query_urls(cfg, kept):
    origin = cfg["origin"]
    urls = [
        f"{_USGS_URL}?starttime={cfg['start']}&endtime={cfg['end']}"
        f"&minmagnitude={cfg['min_magnitude']}&latitude={origin['lat']}"
        f"&longitude={origin['lon']}&maxradiuskm={cfg['event_radius_km']}",
        f"{_STATION_URL}?network={cfg['network']}&channel={','.join(cfg['channels'])}"
        f"&level=channel&starttime={cfg['start']}&endtime={cfg['end']}",
    ]
    urls += [
        f"{_DATASELECT_URL}?network={s['network']}&station={s['station']}"
        f"&location={s['location'] or '--'}&channel={s['channel']}"
        f"&starttime={c['window'][0]}&endtime={c['window'][1]}"
        for c in kept
        for s in c["summary"]["stations"]
    ]
    return urls


def _write(out: Path, kept, cfg, n_candidates, versions) -> None:
    waveforms = out / "waveforms"
    waveforms.mkdir(parents=True, exist_ok=True)
    for old in waveforms.glob("*.npz"):
        old.unlink()
    for c in kept:
        np.savez_compressed(waveforms / f"{c['id']}.npz", **c["arrays"])
    events_path = out / "events.json"
    events_path.write_text(json.dumps([c["summary"] for c in kept], indent=2) + "\n")
    files = [events_path, *sorted(waveforms.glob("*.npz"))]
    manifest = {
        "origin": cfg["origin"],
        "parameters": {k: v for k, v in cfg.items() if k != "origin"},
        "catalog_events_considered": n_candidates,
        "fetched_at": dt.datetime.now(dt.UTC).isoformat(timespec="seconds"),
        "versions": versions,
        "citations": _CITATIONS,
        "query_urls": _query_urls(cfg, kept),
        "files": {p.relative_to(out).as_posix(): _sha256(p) for p in files},
    }
    (out / "MANIFEST.json").write_text(json.dumps(manifest, indent=2, sort_keys=True) + "\n")


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--out", default="data/real")
    parser.add_argument("--config", default="config/realdata.json")
    parser.add_argument("--start")
    parser.add_argument("--end")
    parser.add_argument("--min-mag", type=float)
    parser.add_argument("--max-events", type=int)
    args = parser.parse_args(argv)

    import obspy
    from obspy.clients.fdsn import Client

    cfg = json.loads(Path(args.config).read_text())
    overrides = {
        "start": args.start,
        "end": args.end,
        "min_magnitude": args.min_mag,
        "max_events": args.max_events,
    }
    cfg.update({k: v for k, v in overrides.items() if v is not None})

    usgs, earthscope = Client("USGS"), Client("EARTHSCOPE")
    start, end = obspy.UTCDateTime(cfg["start"]), obspy.UTCDateTime(cfg["end"])
    catalog = usgs.get_events(
        starttime=start,
        endtime=end,
        minmagnitude=cfg["min_magnitude"],
        latitude=cfg["origin"]["lat"],
        longitude=cfg["origin"]["lon"],
        maxradius=cfg["event_radius_km"] / _KM_PER_DEG,
    )
    print(f"{len(catalog)} catalog events")
    inventory = earthscope.get_stations(
        network=cfg["network"],
        channel=",".join(cfg["channels"]),
        level="channel",
        starttime=start,
        endtime=end,
    )
    candidates = []
    for i, event in enumerate(catalog):
        c = _process_event(event, inventory, earthscope, cfg)
        print(
            f"[{i + 1}/{len(catalog)}] {_event_id(event)}: {c['n_stations'] if c else 'rejected'}"
        )
        if c:
            candidates.append(c)
    print(f"{len(candidates)} events qualify")
    if not candidates:
        print("No event qualifies; snapshot not written. See the RUNBOOK on widening the query.")
        return 1
    kept = rank_events(candidates, cfg["max_events"])
    versions = {"obspy": obspy.__version__, "numpy": np.__version__}
    _write(Path(args.out), kept, cfg, len(catalog), versions)
    print(f"Wrote {len(kept)} events to {args.out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
