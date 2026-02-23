"""Coordinate reference system conversions and distance utilities.

Supports conversions between WGS-84 (GPS), GCJ-02 (国测局 / 高德 / 腾讯),
and BD-09 (百度).  All functions are pure math with no external dependencies.

Data source for the GCJ-02 algorithm constants:
https://github.com/googollee/eviltransform (public domain / MIT).
"""
from __future__ import annotations

import math

# ------------------------------------------------------------------
# Constants
# ------------------------------------------------------------------

_A = 6378245.0  # GCJ-02 semi-major axis
_EE = 0.00669342162296594  # GCJ-02 eccentricity squared
_X_PI = math.pi * 3000.0 / 180.0  # BD-09 constant

# Approximate bounding box for mainland China + territories
_LNG_MIN, _LNG_MAX = 72.004, 137.8347
_LAT_MIN, _LAT_MAX = 0.8293, 55.8271

_EARTH_RADIUS_KM = 6371.0

# ------------------------------------------------------------------
# Internal helpers
# ------------------------------------------------------------------


def _out_of_china(lng: float, lat: float) -> bool:
    """Return *True* if the coordinate is outside China's approximate bounds."""
    return not (_LNG_MIN < lng < _LNG_MAX and _LAT_MIN < lat < _LAT_MAX)


def _transform_lat(x: float, y: float) -> float:
    ret = (
        -100.0
        + 2.0 * x
        + 3.0 * y
        + 0.2 * y * y
        + 0.1 * x * y
        + 0.2 * math.sqrt(abs(x))
    )
    ret += (20.0 * math.sin(6.0 * x * math.pi) + 20.0 * math.sin(2.0 * x * math.pi)) * 2.0 / 3.0
    ret += (20.0 * math.sin(y * math.pi) + 40.0 * math.sin(y / 3.0 * math.pi)) * 2.0 / 3.0
    ret += (160.0 * math.sin(y / 12.0 * math.pi) + 320.0 * math.sin(y * math.pi / 30.0)) * 2.0 / 3.0
    return ret


def _transform_lng(x: float, y: float) -> float:
    ret = (
        300.0
        + x
        + 2.0 * y
        + 0.1 * x * x
        + 0.1 * x * y
        + 0.1 * math.sqrt(abs(x))
    )
    ret += (20.0 * math.sin(6.0 * x * math.pi) + 20.0 * math.sin(2.0 * x * math.pi)) * 2.0 / 3.0
    ret += (20.0 * math.sin(x * math.pi) + 40.0 * math.sin(x / 3.0 * math.pi)) * 2.0 / 3.0
    ret += (150.0 * math.sin(x / 12.0 * math.pi) + 300.0 * math.sin(x / 30.0 * math.pi)) * 2.0 / 3.0
    return ret


def _delta(lng: float, lat: float) -> tuple[float, float]:
    """Compute the GCJ-02 offset ``(dlng, dlat)`` for a WGS-84 coordinate."""
    dlat = _transform_lat(lng - 105.0, lat - 35.0)
    dlng = _transform_lng(lng - 105.0, lat - 35.0)
    rad_lat = lat / 180.0 * math.pi
    magic = math.sin(rad_lat)
    magic = 1 - _EE * magic * magic
    sqrt_magic = math.sqrt(magic)
    dlat = (dlat * 180.0) / ((_A * (1 - _EE)) / (magic * sqrt_magic) * math.pi)
    dlng = (dlng * 180.0) / (_A / sqrt_magic * math.cos(rad_lat) * math.pi)
    return dlng, dlat


# ------------------------------------------------------------------
# WGS-84 <-> GCJ-02
# ------------------------------------------------------------------


def wgs84_to_gcj02(lng: float, lat: float) -> tuple[float, float]:
    """Convert WGS-84 to GCJ-02.

    Parameters
    ----------
    lng : float
        Longitude (WGS-84).
    lat : float
        Latitude (WGS-84).

    Returns
    -------
    tuple[float, float]
        ``(lng, lat)`` in GCJ-02.  Coordinates outside China are returned
        unchanged.
    """
    if _out_of_china(lng, lat):
        return lng, lat
    dlng, dlat = _delta(lng, lat)
    return lng + dlng, lat + dlat


def gcj02_to_wgs84(lng: float, lat: float) -> tuple[float, float]:
    """Convert GCJ-02 to WGS-84 (simple subtraction approximation).

    Parameters
    ----------
    lng : float
        Longitude (GCJ-02).
    lat : float
        Latitude (GCJ-02).

    Returns
    -------
    tuple[float, float]
        ``(lng, lat)`` in WGS-84.  Coordinates outside China are returned
        unchanged.
    """
    if _out_of_china(lng, lat):
        return lng, lat
    dlng, dlat = _delta(lng, lat)
    return lng - dlng, lat - dlat


# ------------------------------------------------------------------
# GCJ-02 <-> BD-09
# ------------------------------------------------------------------


def gcj02_to_bd09(lng: float, lat: float) -> tuple[float, float]:
    """Convert GCJ-02 to BD-09.

    Parameters
    ----------
    lng : float
        Longitude (GCJ-02).
    lat : float
        Latitude (GCJ-02).

    Returns
    -------
    tuple[float, float]
        ``(lng, lat)`` in BD-09.
    """
    z = math.sqrt(lng * lng + lat * lat) + 0.00002 * math.sin(lat * _X_PI)
    theta = math.atan2(lat, lng) + 0.000003 * math.cos(lng * _X_PI)
    return z * math.cos(theta) + 0.0065, z * math.sin(theta) + 0.006


def bd09_to_gcj02(lng: float, lat: float) -> tuple[float, float]:
    """Convert BD-09 to GCJ-02.

    Parameters
    ----------
    lng : float
        Longitude (BD-09).
    lat : float
        Latitude (BD-09).

    Returns
    -------
    tuple[float, float]
        ``(lng, lat)`` in GCJ-02.
    """
    x = lng - 0.0065
    y = lat - 0.006
    z = math.sqrt(x * x + y * y) - 0.00002 * math.sin(y * _X_PI)
    theta = math.atan2(y, x) - 0.000003 * math.cos(x * _X_PI)
    return z * math.cos(theta), z * math.sin(theta)


# ------------------------------------------------------------------
# WGS-84 <-> BD-09 (composed via GCJ-02)
# ------------------------------------------------------------------


def wgs84_to_bd09(lng: float, lat: float) -> tuple[float, float]:
    """Convert WGS-84 to BD-09 (via GCJ-02).

    Parameters
    ----------
    lng : float
        Longitude (WGS-84).
    lat : float
        Latitude (WGS-84).

    Returns
    -------
    tuple[float, float]
        ``(lng, lat)`` in BD-09.
    """
    return gcj02_to_bd09(*wgs84_to_gcj02(lng, lat))


def bd09_to_wgs84(lng: float, lat: float) -> tuple[float, float]:
    """Convert BD-09 to WGS-84 (via GCJ-02).

    Parameters
    ----------
    lng : float
        Longitude (BD-09).
    lat : float
        Latitude (BD-09).

    Returns
    -------
    tuple[float, float]
        ``(lng, lat)`` in WGS-84.
    """
    return gcj02_to_wgs84(*bd09_to_gcj02(lng, lat))


# ------------------------------------------------------------------
# Distance
# ------------------------------------------------------------------


def distance(lat1: float, lng1: float, lat2: float, lng2: float) -> float:
    """Great-circle distance between two points using the Haversine formula.

    Parameters
    ----------
    lat1, lng1 : float
        Latitude and longitude of the first point (degrees, WGS-84).
    lat2, lng2 : float
        Latitude and longitude of the second point (degrees, WGS-84).

    Returns
    -------
    float
        Distance in kilometres.
    """
    lat1_r = math.radians(lat1)
    lat2_r = math.radians(lat2)
    dlat = math.radians(lat2 - lat1)
    dlng = math.radians(lng2 - lng1)
    a = (
        math.sin(dlat / 2) ** 2
        + math.cos(lat1_r) * math.cos(lat2_r) * math.sin(dlng / 2) ** 2
    )
    return _EARTH_RADIUS_KM * 2 * math.atan2(math.sqrt(a), math.sqrt(1 - a))
