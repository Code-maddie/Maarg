"""Phase 2 validation: the haversine stand-in for PostGIS ST_DWithin."""

import pytest

from app.core.geo import bounding_box, haversine_km, path_length_km, within_radius

# Reference great-circle distances (km), accurate to well under 1%.
DELHI = (28.6139, 77.2090)
MUMBAI = (19.0760, 72.8777)
BENGALURU = (12.9716, 77.5946)


def test_zero_distance_to_self() -> None:
    assert haversine_km(*DELHI, *DELHI) == pytest.approx(0.0, abs=1e-9)


def test_delhi_to_mumbai_matches_reference() -> None:
    # Published great-circle distance is ~1153 km.
    assert haversine_km(*DELHI, *MUMBAI) == pytest.approx(1153, rel=0.01)


def test_delhi_to_bengaluru_matches_reference() -> None:
    # Published great-circle distance is ~1740 km.
    assert haversine_km(*DELHI, *BENGALURU) == pytest.approx(1740, rel=0.01)


def test_distance_is_symmetric() -> None:
    assert haversine_km(*DELHI, *MUMBAI) == pytest.approx(
        haversine_km(*MUMBAI, *DELHI)
    )


def test_one_degree_of_latitude_is_about_111km() -> None:
    assert haversine_km(0.0, 0.0, 1.0, 0.0) == pytest.approx(111.19, rel=0.01)


def test_bounding_box_contains_the_centre() -> None:
    min_lat, max_lat, min_lng, max_lng = bounding_box(*DELHI, 100)
    assert min_lat < DELHI[0] < max_lat
    assert min_lng < DELHI[1] < max_lng


def test_bounding_box_widens_in_longitude_near_the_pole() -> None:
    _, _, eq_min_lng, eq_max_lng = bounding_box(0.0, 0.0, 100)
    _, _, pol_min_lng, pol_max_lng = bounding_box(80.0, 0.0, 100)
    assert (pol_max_lng - pol_min_lng) > (eq_max_lng - eq_min_lng)


def test_bounding_box_survives_the_pole() -> None:
    min_lat, max_lat, min_lng, max_lng = bounding_box(90.0, 0.0, 100)
    assert max_lat <= 90.0 and min_lat >= -90.0
    assert min_lng >= -180.0 and max_lng <= 180.0


def test_within_radius_selects_and_orders_by_distance(hubs) -> None:
    # 1300 km of Delhi reaches Mumbai (~1153) but not Bengaluru (~1740).
    near = within_radius(hubs, *DELHI, 1300)
    assert [h.code for h in near] == ["DEL", "BOM"]


def test_within_radius_excludes_everything_when_tiny(hubs) -> None:
    assert within_radius(hubs, *DELHI, 1) == [hubs[0]]


def test_path_length_sums_the_hops() -> None:
    total = path_length_km([DELHI, MUMBAI, BENGALURU])
    expected = haversine_km(*DELHI, *MUMBAI) + haversine_km(*MUMBAI, *BENGALURU)
    assert total == pytest.approx(expected)


def test_path_length_of_single_point_is_zero() -> None:
    assert path_length_km([DELHI]) == 0.0
