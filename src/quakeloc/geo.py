"""Spherical azimuthal-equidistant projection and great-circle distance."""

import math

EARTH_RADIUS_KM = 6371.0


def haversine_km(lat1, lon1, lat2, lon2) -> float:
    p1, p2 = math.radians(lat1), math.radians(lat2)
    dp, dl = p2 - p1, math.radians(lon2 - lon1)
    a = math.sin(dp / 2) ** 2 + math.cos(p1) * math.cos(p2) * math.sin(dl / 2) ** 2
    return 2 * EARTH_RADIUS_KM * math.asin(math.sqrt(a))


def aeqd_forward(lat, lon, lat0, lon0) -> tuple[float, float]:
    """(lat, lon) in degrees to (x east, y north) in km about (lat0, lon0)."""
    p, p0 = math.radians(lat), math.radians(lat0)
    dl = math.radians(lon - lon0)
    c = haversine_km(lat, lon, lat0, lon0) / EARTH_RADIUS_KM
    k = c / math.sin(c) if c > 1e-12 else 1.0
    x = k * math.cos(p) * math.sin(dl)
    y = k * (math.cos(p0) * math.sin(p) - math.sin(p0) * math.cos(p) * math.cos(dl))
    return EARTH_RADIUS_KM * x, EARTH_RADIUS_KM * y


def aeqd_inverse(x_km, y_km, lat0, lon0) -> tuple[float, float]:
    p0 = math.radians(lat0)
    rho = math.hypot(x_km, y_km)
    if rho < 1e-9:
        return float(lat0), float(lon0)
    c = rho / EARTH_RADIUS_KM
    sin_c, cos_c = math.sin(c), math.cos(c)
    lat = math.asin(cos_c * math.sin(p0) + y_km * sin_c * math.cos(p0) / rho)
    dl = math.atan2(x_km * sin_c, rho * math.cos(p0) * cos_c - y_km * math.sin(p0) * sin_c)
    return math.degrees(lat), lon0 + math.degrees(dl)
