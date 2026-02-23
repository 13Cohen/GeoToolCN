"""Tests for GeoToolCN."""

import pytest

from GeoToolCN import (
    GeoTool,
    Region,
    ReverseResult,
    get_region,
    list_regions,
    reverse,
    reverse_batch,
    search,
)


@pytest.fixture(scope="module")
def geo() -> GeoTool:
    return GeoTool()


# ---------------------------------------------------------------
# Reverse geocoding
# ---------------------------------------------------------------


class TestReverse:
    def test_beijing(self, geo: GeoTool) -> None:
        r = geo.reverse(39.9, 116.4)
        assert isinstance(r, ReverseResult)
        assert r.province is not None
        assert "北京" in r.province.name

    def test_shanghai(self, geo: GeoTool) -> None:
        r = geo.reverse(31.2, 121.5)
        assert r.province is not None
        assert "上海" in r.province.name

    def test_out_of_china(self, geo: GeoTool) -> None:
        r = geo.reverse(0.0, 0.0)
        assert r.province is None
        assert r.city is None
        assert r.district is None

    def test_result_has_codes(self, geo: GeoTool) -> None:
        r = geo.reverse(39.9, 116.4)
        assert r.province is not None
        assert r.province.code.isdigit()


# ---------------------------------------------------------------
# Batch reverse geocoding
# ---------------------------------------------------------------


class TestReverseBatch:
    def test_multiple(self, geo: GeoTool) -> None:
        results = geo.reverse_batch([(39.9, 116.4), (31.2, 121.5)])
        assert len(results) == 2
        assert "北京" in results[0].province.name
        assert "上海" in results[1].province.name

    def test_empty(self, geo: GeoTool) -> None:
        assert geo.reverse_batch([]) == []

    def test_mixed_hits_and_misses(self, geo: GeoTool) -> None:
        results = geo.reverse_batch([(39.9, 116.4), (0.0, 0.0)])
        assert results[0].province is not None
        assert results[1].province is None


# ---------------------------------------------------------------
# Forward geocoding / search
# ---------------------------------------------------------------


class TestSearch:
    def test_by_name_exact(self, geo: GeoTool) -> None:
        results = geo.search("深圳市")
        assert len(results) >= 1
        assert results[0].name == "深圳市"
        assert results[0].level == "city"

    def test_by_code(self, geo: GeoTool) -> None:
        results = geo.search("156110000")
        assert len(results) >= 1
        assert "北京" in results[0].name

    def test_by_name_fuzzy(self, geo: GeoTool) -> None:
        results = geo.search("深圳")
        assert any("深圳" in r.name for r in results)

    def test_fuzzy_disabled(self, geo: GeoTool) -> None:
        results = geo.search("深圳", fuzzy=False)
        assert all(r.name == "深圳" for r in results) or len(results) == 0

    def test_level_filter(self, geo: GeoTool) -> None:
        results = geo.search("朝阳区", level="district")
        assert all(r.level == "district" for r in results)

    def test_no_match(self, geo: GeoTool) -> None:
        results = geo.search("不存在的地方xyz")
        assert results == []

    def test_has_coordinates(self, geo: GeoTool) -> None:
        results = geo.search("深圳市")
        r = results[0]
        assert r.latitude is not None
        assert r.longitude is not None

    def test_filter_by_province_name(self, geo: GeoTool) -> None:
        all_results = geo.search("朝阳区", level="district")
        assert len(all_results) >= 2  # Beijing + Changchun
        beijing_only = geo.search("朝阳区", province="北京市")
        assert len(beijing_only) == 1
        assert beijing_only[0].code == "156110105"

    def test_filter_by_province_code(self, geo: GeoTool) -> None:
        results = geo.search("朝阳区", province="156110000")
        assert len(results) == 1
        assert results[0].code == "156110105"

    def test_filter_by_city(self, geo: GeoTool) -> None:
        results = geo.search("朝阳区", city="长春市")
        assert len(results) == 1
        assert results[0].code == "156220104"

    def test_filter_no_match(self, geo: GeoTool) -> None:
        results = geo.search("朝阳区", province="广东省")
        assert results == []


# ---------------------------------------------------------------
# Region listing / lookup
# ---------------------------------------------------------------


class TestListRegions:
    def test_provinces(self, geo: GeoTool) -> None:
        provinces = geo.list_regions("province")
        assert len(provinces) > 30
        assert all(isinstance(r, Region) for r in provinces)
        assert all(r.level == "province" for r in provinces)

    def test_invalid_level(self, geo: GeoTool) -> None:
        with pytest.raises(ValueError):
            geo.list_regions("country")


class TestGetRegion:
    def test_found(self, geo: GeoTool) -> None:
        r = geo.get_region("156110000")
        assert r is not None
        assert "北京" in r.name

    def test_not_found(self, geo: GeoTool) -> None:
        assert geo.get_region("999999999") is None


# ---------------------------------------------------------------
# Module-level convenience functions
# ---------------------------------------------------------------


class TestConvenienceFunctions:
    def test_reverse(self) -> None:
        r = reverse(39.9, 116.4)
        assert r.province is not None

    def test_search(self) -> None:
        results = search("深圳市")
        assert len(results) >= 1

    def test_reverse_batch(self) -> None:
        results = reverse_batch([(39.9, 116.4)])
        assert len(results) == 1

    def test_list_regions(self) -> None:
        provinces = list_regions("province")
        assert len(provinces) > 0

    def test_get_region(self) -> None:
        r = get_region("156110000")
        assert r is not None
