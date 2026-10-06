"""Route geometry for the map layer.

Legs are drawn as the same gentle quadratic curve the existing frontend
already uses (`legPoints` in map.js), so moving the geometry server-side
changes nothing visually. Geometry is also emitted as a Google encoded
polyline, the format SH.docx §6.1 attaches to each `google.maps.Polyline`.
"""

from __future__ import annotations

from typing import Iterable, List, Sequence, Tuple

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models import Hub, Leg

LatLng = Tuple[float, float]

# Must match map.js legPoints(): 28 segments, control-point offset 0.13.
CURVE_SEGMENTS = 28
CURVE_BEND = 0.13


def leg_curve(
    a: LatLng, b: LatLng, *, n: int = CURVE_SEGMENTS, bend: float = CURVE_BEND
) -> List[LatLng]:
    """Quadratic Bézier from ``a`` to ``b`` — identical to map.js legPoints()."""
    d_lat, d_lng = b[0] - a[0], b[1] - a[1]
    control = ((a[0] + b[0]) / 2 - d_lng * bend, (a[1] + b[1]) / 2 + d_lat * bend)

    points: List[LatLng] = []
    for i in range(n + 1):
        t = i / n
        u = 1 - t
        points.append(
            (
                u * u * a[0] + 2 * u * t * control[0] + t * t * b[0],
                u * u * a[1] + 2 * u * t * control[1] + t * t * b[1],
            )
        )
    return points


def point_along(points: Sequence[LatLng], t: float) -> LatLng:
    """Position a fraction ``t`` of the way along a polyline (by vertex)."""
    t = max(0.0, min(1.0, t))
    f = t * (len(points) - 1)
    i = min(len(points) - 2, int(f))
    u = f - i
    return (
        points[i][0] + (points[i + 1][0] - points[i][0]) * u,
        points[i][1] + (points[i + 1][1] - points[i][1]) * u,
    )


# --- Google encoded polyline (precision 5) -------------------------------

def _encode_value(value: int) -> str:
    value = ~(value << 1) if value < 0 else value << 1
    chunks = []
    while value >= 0x20:
        chunks.append(chr((0x20 | (value & 0x1F)) + 63))
        value >>= 5
    chunks.append(chr(value + 63))
    return "".join(chunks)


def encode_polyline(points: Iterable[LatLng]) -> str:
    """Encodes points with Google's polyline algorithm.

    Decodable client-side with ``google.maps.geometry.encoding.decodePath``.
    """
    result = []
    prev_lat = prev_lng = 0
    for lat, lng in points:
        lat_i, lng_i = round(lat * 1e5), round(lng * 1e5)
        result.append(_encode_value(lat_i - prev_lat))
        result.append(_encode_value(lng_i - prev_lng))
        prev_lat, prev_lng = lat_i, lng_i
    return "".join(result)


def decode_polyline(encoded: str) -> List[LatLng]:
    """Inverse of :func:`encode_polyline`."""
    points: List[LatLng] = []
    index = lat = lng = 0

    while index < len(encoded):
        for is_lng in (False, True):
            shift = result = 0
            while True:
                byte = ord(encoded[index]) - 63
                index += 1
                result |= (byte & 0x1F) << shift
                shift += 5
                if byte < 0x20:
                    break
            delta = ~(result >> 1) if result & 1 else result >> 1
            if is_lng:
                lng += delta
            else:
                lat += delta
        points.append((lat / 1e5, lng / 1e5))

    return points


def backfill_leg_polylines(db: Session, *, overwrite: bool = False) -> int:
    """Stores the encoded curve on every leg that lacks one. Returns count."""
    hubs = {hub.id: hub for hub in db.scalars(select(Hub)).all()}
    updated = 0

    for leg in db.scalars(select(Leg)).all():
        if leg.polyline and not overwrite:
            continue
        a, b = hubs.get(leg.from_hub_id), hubs.get(leg.to_hub_id)
        if a is None or b is None:
            continue
        leg.polyline = encode_polyline(leg_curve((a.lat, a.lng), (b.lat, b.lng)))
        updated += 1

    if updated:
        db.commit()
    return updated
