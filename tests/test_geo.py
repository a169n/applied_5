import pytest

from quakeloc.geo import aeqd_forward, aeqd_inverse, haversine_km

LAT0, LON0 = 42.58, 74.78


@pytest.mark.parametrize("lat,lon", [(43.5, 76.0), (41.0, 73.0), (42.58, 75.5), (44.0, 74.78)])
def test_aeqd_roundtrip(lat, lon):
    x, y = aeqd_forward(lat, lon, LAT0, LON0)
    lat2, lon2 = aeqd_inverse(x, y, LAT0, LON0)
    assert lat2 == pytest.approx(lat, abs=1e-9) and lon2 == pytest.approx(lon, abs=1e-9)


def test_aeqd_at_origin_is_zero():
    assert aeqd_forward(LAT0, LON0, LAT0, LON0) == pytest.approx((0.0, 0.0), abs=1e-12)
    assert aeqd_inverse(0.0, 0.0, LAT0, LON0) == pytest.approx((LAT0, LON0), abs=1e-12)


def test_aeqd_axes_point_east_and_north():
    x, y = aeqd_forward(LAT0, LON0 + 0.5, LAT0, LON0)
    assert x > 0 and abs(y) < 1
    x, y = aeqd_forward(LAT0 + 0.5, LON0, LAT0, LON0)
    assert y > 0 and abs(x) < 1e-9


def test_haversine_one_degree_equator():
    assert haversine_km(0, 0, 0, 1) == pytest.approx(111.195, abs=1e-3)


def test_aeqd_preserves_distance_from_origin():
    x, y = aeqd_forward(43.2, 75.9, LAT0, LON0)
    assert (x**2 + y**2) ** 0.5 == pytest.approx(haversine_km(LAT0, LON0, 43.2, 75.9), rel=1e-9)


def test_aeqd_distance_error_under_0p2_percent():
    # Event 100 km off-centre, station 150 km from the event: the spec's worst geometry.
    ev = aeqd_inverse(100.0, 0.0, LAT0, LON0)
    sta = aeqd_inverse(100.0, 150.0, LAT0, LON0)
    projected = 150.0
    assert abs(projected - haversine_km(*ev, *sta)) / projected < 0.002
