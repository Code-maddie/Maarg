"""Geographic helpers.

`SH.docx` specifies PostGIS `ST_DWithin` for the Piggy Router's geo-pruning
step. The prototype runs on SQLite, so the same pruning is done with a
haversine distance plus a bounding-box pre-filter. At prototype scale
(30 hubs, 200 vehicles, 5 000 shipments) the two are interchangeable.
"""

from __future__ import annotations

import math
from typing import Iterable, List, Sequence, Tuple, TypeVar

EARTH_RADIUS_KM = 6371.0088

T = TypeVar("T")


def haversine_km(lat1: float, lng1: float, lat2: float, lng2: float) -> float:
    """Great-circle distance between two WGS-84 points, in kilometres."""
    phi1, phi2 = math.radians(lat1), math.radians(lat2)
    d_phi = phi2 - phi1
    d_lambda = math.radians(lng2 - lng1)

    a = (
        math.sin(d_phi / 2) ** 2
        + math.cos(phi1) * math.cos(phi2) * math.sin(d_lambda / 2) ** 2
    )
    return 2 * EARTH_RADIUS_KM * math.asin(math.sqrt(min(1.0, a)))


def bounding_box(
    lat: float, lng: float, radius_km: float
) -> Tuple[float, float, float, float]:
    """Returns ``(min_lat, max_lat, min_lng, max_lng)`` enclosing the radius.

    Used as a cheap SQL pre-filter before the exact haversine check, which is
    what makes this a practical stand-in for ``ST_DWithin``.
    """
    lat_delta = math.degrees(radius_km / EARTH_RADIUS_KM)

    # Longitude degrees shrink toward the poles; guard the degenerate case.
    cos_lat = math.cos(math.radians(lat))
    if abs(cos_lat) < 1e-9:
        lng_delta = 180.0
    else:
        lng_delta = math.degrees(radius_km / (EARTH_RADIUS_KM * abs(cos_lat)))

    return (
        max(-90.0, lat - lat_delta),
        min(90.0, lat + lat_delta),
        max(-180.0, lng - lng_delta),
        min(180.0, lng + lng_delta),
    )


def within_radius(
    items: Iterable[T],
    lat: float,
    lng: float,
    radius_km: float,
    *,
    lat_attr: str = "lat",
    lng_attr: str = "lng",
) -> List[T]:
    """Filters ``items`` to those within ``radius_km``, nearest first."""
    matched: List[Tuple[float, T]] = []
    for item in items:
        distance = haversine_km(
            lat, lng, getattr(item, lat_attr), getattr(item, lng_attr)
        )
        if distance <= radius_km:
            matched.append((distance, item))

    matched.sort(key=lambda pair: pair[0])
    return [item for _, item in matched]


def path_length_km(points: Sequence[Tuple[float, float]]) -> float:
    """Total great-circle length of an ordered ``(lat, lng)`` polyline."""
    return sum(
        haversine_km(points[i][0], points[i][1], points[i + 1][0], points[i + 1][1])
        for i in range(len(points) - 1)
    )
