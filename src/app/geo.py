"""Geographic helpers shared by the map entities (shops, restaurants)."""
import math
from typing import Tuple

EARTH_RADIUS_METERS = 6371000
METERS_PER_DEGREE_LAT = 111320


def haversine_distance(lat1: float, lon1: float, lat2: float, lon2: float) -> float:
    """
    Distance in meters between two points using the Haversine formula.
    https://en.wikipedia.org/wiki/Haversine_formula
    """
    a = (math.sin(math.radians(lat2 - lat1) / 2) ** 2 +
         math.cos(math.radians(lat1)) * math.cos(math.radians(lat2)) *
         math.sin(math.radians(lon2 - lon1) / 2) ** 2)
    c = 2 * math.atan2(math.sqrt(a), math.sqrt(1 - a))
    return EARTH_RADIUS_METERS * c


def bounding_box_deltas(latitude: float, radius_meters: int) -> Tuple[float, float]:
    """
    Approximate (lat, lon) half-sizes in degrees of a box containing a circle
    of the given radius, to pre-filter rows before the exact distance check.
    """
    lat_range = radius_meters / METERS_PER_DEGREE_LAT
    lon_range = radius_meters / \
        (METERS_PER_DEGREE_LAT * math.cos(math.radians(latitude)))
    return lat_range, lon_range
