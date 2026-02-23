"""Post-install smoke tests — validate the public API as an end user would.

Run after ``pip install geotool-cn`` (or ``pip install -e .``) to verify that
the package is correctly installed and all advertised features work.

Usage::

    pytest tests/smoke/ -v
"""
from __future__ import annotations

import GeoToolCN

# ---------------------------------------------------------------
# Package metadata
# ---------------------------------------------------------------


class TestPackageMeta:
    def test_version(self) -> None:
        assert hasattr(GeoToolCN, "__version__")
        assert isinstance(GeoToolCN.__version__, str)

    def test_all_exports_importable(self) -> None:
        for name in GeoToolCN.__all__:
            assert hasattr(GeoToolCN, name), f"{name!r} listed in __all__ but not importable"


# ---------------------------------------------------------------
# Reverse geocoding
# ---------------------------------------------------------------


class TestReverse:
    def test_reverse(self) -> None:
        r = GeoToolCN.reverse(39.9, 116.4)
        assert r.province is not None
        assert "北京" in r.province.name
        assert r.province.code.startswith("156")

    def test_reverse_miss(self) -> None:
        r = GeoToolCN.reverse(0.0, 0.0)
        assert r.province is None

    def test_reverse_batch(self) -> None:
        results = GeoToolCN.reverse_batch([(39.9, 116.4), (31.2, 121.5)])
        assert len(results) == 2
        assert "北京" in results[0].province.name
        assert "上海" in results[1].province.name


# ---------------------------------------------------------------
# Forward geocoding
# ---------------------------------------------------------------


class TestSearch:
    def test_by_name(self) -> None:
        results = GeoToolCN.search("深圳市")
        assert len(results) >= 1
        assert results[0].name == "深圳市"

    def test_by_code(self) -> None:
        results = GeoToolCN.search("156440300")
        assert len(results) >= 1
        assert "深圳" in results[0].name


# ---------------------------------------------------------------
# Region listing / lookup
# ---------------------------------------------------------------


class TestRegions:
    def test_list_regions(self) -> None:
        provinces = GeoToolCN.list_regions("province")
        assert len(provinces) > 30

    def test_get_region(self) -> None:
        r = GeoToolCN.get_region("156110000")
        assert r is not None
        assert isinstance(r, GeoToolCN.Region)


# ---------------------------------------------------------------
# Administrative tree
# ---------------------------------------------------------------


class TestAdminTree:
    def test_tree_structure(self) -> None:
        tree = GeoToolCN.get_administrative_tree()
        assert isinstance(tree, list)
        assert len(tree) == 34
        node = tree[0]
        assert "value" in node and "label" in node and "children" in node


# ---------------------------------------------------------------
# Adcode lookup
# ---------------------------------------------------------------


class TestLookupAdcode:
    def test_district(self) -> None:
        r = GeoToolCN.lookup_adcode("110108")
        assert r is not None
        assert isinstance(r, GeoToolCN.ReverseResult)
        assert r.province is not None and "北京" in r.province.name
        assert r.district is not None and "海淀" in r.district.name

    def test_city(self) -> None:
        r = GeoToolCN.lookup_adcode("440300")
        assert r is not None
        assert "深圳" in r.city.name
        assert r.district is None

    def test_invalid(self) -> None:
        assert GeoToolCN.lookup_adcode("999999") is None


# ---------------------------------------------------------------
# Coordinate conversion
# ---------------------------------------------------------------


class TestCoordConversion:
    def test_wgs84_gcj02_roundtrip(self) -> None:
        lng, lat = 116.3, 39.9
        gcj = GeoToolCN.wgs84_to_gcj02(lng, lat)
        assert gcj != (lng, lat)
        back = GeoToolCN.gcj02_to_wgs84(*gcj)
        assert abs(back[0] - lng) < 0.001
        assert abs(back[1] - lat) < 0.001

    def test_bd09_gcj02_roundtrip(self) -> None:
        lng, lat = 116.3, 39.9
        bd = GeoToolCN.gcj02_to_bd09(lng, lat)
        back = GeoToolCN.bd09_to_gcj02(*bd)
        assert abs(back[0] - lng) < 0.0001
        assert abs(back[1] - lat) < 0.0001

    def test_wgs84_bd09_roundtrip(self) -> None:
        lng, lat = 116.3, 39.9
        bd = GeoToolCN.wgs84_to_bd09(lng, lat)
        back = GeoToolCN.bd09_to_wgs84(*bd)
        assert abs(back[0] - lng) < 0.001
        assert abs(back[1] - lat) < 0.001

    def test_outside_china_passthrough(self) -> None:
        assert GeoToolCN.wgs84_to_gcj02(0.0, 0.0) == (0.0, 0.0)


# ---------------------------------------------------------------
# Distance
# ---------------------------------------------------------------


class TestDistance:
    def test_known_distance(self) -> None:
        km = GeoToolCN.distance(32.06, 118.79, 31.23, 121.47)
        assert 250 < km < 290  # Nanjing -> Shanghai ~271 km

    def test_same_point(self) -> None:
        assert GeoToolCN.distance(39.9, 116.3, 39.9, 116.3) == 0.0


# ---------------------------------------------------------------
# Containment checks
# ---------------------------------------------------------------


class TestContainment:
    def test_is_in_china(self) -> None:
        assert GeoToolCN.is_in_china(39.9, 116.4) is True
        assert GeoToolCN.is_in_china(35.68, 139.69) is False

    def test_is_in_region(self) -> None:
        assert GeoToolCN.is_in_region(22.55, 114.06, "440300") is True
        assert GeoToolCN.is_in_region(39.9, 116.4, "440300") is False
