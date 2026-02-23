"""Tests for coordinate conversions and distance calculation."""
from __future__ import annotations

from GeoToolCN.coords import (
    bd09_to_gcj02,
    bd09_to_wgs84,
    distance,
    gcj02_to_bd09,
    gcj02_to_wgs84,
    wgs84_to_bd09,
    wgs84_to_gcj02,
)


# ---------------------------------------------------------------
# WGS-84 <-> GCJ-02
# ---------------------------------------------------------------


class TestWgs84ToGcj02:
    def test_known_offset(self) -> None:
        lng, lat = wgs84_to_gcj02(116.3, 39.9)
        assert (lng, lat) != (116.3, 39.9)
        assert abs(lng - 116.3) < 0.01
        assert abs(lat - 39.9) < 0.01

    def test_outside_china(self) -> None:
        assert wgs84_to_gcj02(0.0, 0.0) == (0.0, 0.0)
        assert wgs84_to_gcj02(139.69, 35.68) == (139.69, 35.68)


class TestGcj02ToWgs84:
    def test_roundtrip(self) -> None:
        lng, lat = 116.3, 39.9
        gcj_lng, gcj_lat = wgs84_to_gcj02(lng, lat)
        wgs_lng, wgs_lat = gcj02_to_wgs84(gcj_lng, gcj_lat)
        assert abs(wgs_lng - lng) < 0.001
        assert abs(wgs_lat - lat) < 0.001

    def test_outside_china(self) -> None:
        assert gcj02_to_wgs84(0.0, 0.0) == (0.0, 0.0)


# ---------------------------------------------------------------
# GCJ-02 <-> BD-09
# ---------------------------------------------------------------


class TestGcj02ToBd09:
    def test_known_offset(self) -> None:
        lng, lat = gcj02_to_bd09(116.3, 39.9)
        assert abs(lng - 116.3) < 0.02
        assert abs(lat - 39.9) < 0.02

    def test_roundtrip(self) -> None:
        lng, lat = 116.3, 39.9
        bd_lng, bd_lat = gcj02_to_bd09(lng, lat)
        back_lng, back_lat = bd09_to_gcj02(bd_lng, bd_lat)
        assert abs(back_lng - lng) < 0.0001
        assert abs(back_lat - lat) < 0.0001


# ---------------------------------------------------------------
# WGS-84 <-> BD-09
# ---------------------------------------------------------------


class TestWgs84ToBd09:
    def test_composed(self) -> None:
        lng, lat = 116.3, 39.9
        direct = wgs84_to_bd09(lng, lat)
        step1 = wgs84_to_gcj02(lng, lat)
        step2 = gcj02_to_bd09(*step1)
        assert abs(direct[0] - step2[0]) < 1e-10
        assert abs(direct[1] - step2[1]) < 1e-10

    def test_roundtrip(self) -> None:
        lng, lat = 116.3, 39.9
        bd_lng, bd_lat = wgs84_to_bd09(lng, lat)
        back_lng, back_lat = bd09_to_wgs84(bd_lng, bd_lat)
        assert abs(back_lng - lng) < 0.001
        assert abs(back_lat - lat) < 0.001


# ---------------------------------------------------------------
# Distance
# ---------------------------------------------------------------


class TestDistance:
    def test_same_point(self) -> None:
        assert distance(39.9, 116.3, 39.9, 116.3) == 0.0

    def test_known_distance(self) -> None:
        """Beijing to Shanghai: ~1060 km."""
        d = distance(39.9, 116.4, 31.2, 121.5)
        assert 1000 < d < 1200

    def test_nanjing_to_shanghai(self) -> None:
        """Nanjing to Shanghai: ~270 km."""
        d = distance(32.06, 118.79, 31.23, 121.47)
        assert 250 < d < 290

    def test_symmetry(self) -> None:
        d1 = distance(39.9, 116.4, 31.2, 121.5)
        d2 = distance(31.2, 121.5, 39.9, 116.4)
        assert abs(d1 - d2) < 1e-10
