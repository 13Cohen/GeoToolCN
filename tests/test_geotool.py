"""Tests for GeoToolCN."""

import pytest

from GeoToolCN import (
    GeoTool,
    Region,
    ReverseResult,
    get_region,
    is_in_china,
    is_in_region,
    list_regions,
    lookup_adcode,
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
        results = geo.search("110000")
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
        assert beijing_only[0].code == "110105"

    def test_filter_by_province_code(self, geo: GeoTool) -> None:
        results = geo.search("朝阳区", province="110000")
        assert len(results) == 1
        assert results[0].code == "110105"

    def test_filter_by_city(self, geo: GeoTool) -> None:
        results = geo.search("朝阳区", city="长春市")
        assert len(results) == 1
        assert results[0].code == "220104"

    def test_filter_no_match(self, geo: GeoTool) -> None:
        results = geo.search("朝阳区", province="广东省")
        assert results == []


# ---------------------------------------------------------------
# Region listing / lookup
# ---------------------------------------------------------------


class TestSearchEdgeCases:
    def test_municipality_as_city_filter(self, geo: GeoTool) -> None:
        # reverse() and the tree report 北京市 / 110000 as the city; the
        # filter must accept what they hand back (SPEC §2.4).
        assert [r.code for r in geo.search("朝阳区", city="北京市")] == ["110105"]
        assert [r.code for r in geo.search("朝阳区", city="110000")] == ["110105"]
        assert [r.code for r in geo.search("朝阳区", city="长春市")] == ["220104"]
        # A province that is not a municipality is still not a city.
        assert geo.search("朝阳区", city="广东省") == []

    @pytest.mark.parametrize("query", ["", " ", "\t\n"])
    def test_blank_query_is_empty(self, geo: GeoTool, query: str) -> None:
        assert geo.search(query) == []
        assert geo.search(query, level="province") == []

    def test_fullwidth_digits_are_not_an_adcode(self, geo: GeoTool) -> None:
        assert geo.search("１１００００") == []
        assert geo.search("110000")[0].code == "110000"

    def test_invalid_level_raises(self, geo: GeoTool) -> None:
        with pytest.raises(ValueError):
            geo.search("x", level="county")

    def test_non_string_query_raises(self, geo: GeoTool) -> None:
        with pytest.raises(TypeError):
            geo.search(110000)  # type: ignore[arg-type]


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
        r = geo.get_region("110000")
        assert r is not None
        assert "北京" in r.name

    def test_not_found(self, geo: GeoTool) -> None:
        assert geo.get_region("999999") is None


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
        r = get_region("110000")
        assert r is not None

    def test_lookup_adcode(self) -> None:
        r = lookup_adcode("440305")
        assert r is not None

    def test_is_in_china(self) -> None:
        assert is_in_china(39.9, 116.4) is True

    def test_is_in_region(self) -> None:
        assert is_in_region(39.9, 116.4, "110000") is True


# ---------------------------------------------------------------
# Adcode lookup
# ---------------------------------------------------------------


class TestLookupAdcode:
    def test_normal_district(self, geo: GeoTool) -> None:
        """Shenzhen Nanshan: adcode 440305."""
        r = geo.lookup_adcode("440305")
        assert r is not None
        assert r.province is not None and "广东" in r.province.name
        assert r.city is not None and "深圳" in r.city.name
        assert r.district is not None and "南山" in r.district.name

    def test_normal_city(self, geo: GeoTool) -> None:
        """Shenzhen: adcode 440300."""
        r = geo.lookup_adcode("440300")
        assert r is not None
        assert r.province is not None and "广东" in r.province.name
        assert r.city is not None and "深圳" in r.city.name
        assert r.district is None

    def test_province(self, geo: GeoTool) -> None:
        """Guangdong: adcode 440000."""
        r = geo.lookup_adcode("440000")
        assert r is not None
        assert r.province is not None and "广东" in r.province.name
        assert r.city is None
        assert r.district is None

    def test_municipality_district(self, geo: GeoTool) -> None:
        """Beijing Haidian: adcode 110108."""
        r = geo.lookup_adcode("110108")
        assert r is not None
        assert r.province is not None and "北京" in r.province.name
        assert r.city is not None and "北京" in r.city.name
        assert r.city.level == "city"
        assert r.district is not None and "海淀" in r.district.name

    def test_municipality_has_no_city_level_code(self, geo: GeoTool) -> None:
        """110100 names nothing: a municipality's city *is* the province.

        SPEC §2.7 — the level an adcode's shape implies must exist. 3.0.0
        answered with province + city, while is_in_region rejected the same
        code as unknown; the two now agree.
        """
        assert geo.lookup_adcode("110100") is None
        with pytest.raises(ValueError):
            geo.is_in_region(39.9, 116.4, "110100")
        r = geo.lookup_adcode("110108")
        assert r is not None and r.city is not None
        assert r.city.code == "110000" and r.city.level == "city"

    @pytest.mark.parametrize("code", ["440399", "110199", "419000", "990000"])
    def test_unknown_at_level_is_none(self, geo: GeoTool, code: str) -> None:
        # A partial chain (the province alone for 440399) made `is not None`
        # useless as an existence test.
        assert geo.lookup_adcode(code) is None

    def test_non_string_is_none(self, geo: GeoTool) -> None:
        assert geo.lookup_adcode(110108) is None  # type: ignore[arg-type]
        assert geo.get_region(110000) is None  # type: ignore[arg-type]
        assert geo.lookup_adcode("１１０１０８") is None

    def test_sar(self, geo: GeoTool) -> None:
        """Hong Kong province level."""
        r = geo.lookup_adcode("810000")
        assert r is not None
        assert "香港" in r.province.name

    def test_invalid_format(self, geo: GeoTool) -> None:
        assert geo.lookup_adcode("abc") is None
        assert geo.lookup_adcode("12345") is None
        assert geo.lookup_adcode("") is None

    def test_nonexistent(self, geo: GeoTool) -> None:
        assert geo.lookup_adcode("999999") is None

    def test_returns_reverse_result(self, geo: GeoTool) -> None:
        r = geo.lookup_adcode("110108")
        assert isinstance(r, ReverseResult)


# ---------------------------------------------------------------
# Containment checks
# ---------------------------------------------------------------


class TestIsInChina:
    def test_beijing(self, geo: GeoTool) -> None:
        assert geo.is_in_china(39.9, 116.4) is True

    def test_shenzhen(self, geo: GeoTool) -> None:
        assert geo.is_in_china(22.55, 114.06) is True

    def test_ocean(self, geo: GeoTool) -> None:
        assert geo.is_in_china(0.0, 0.0) is False

    def test_tokyo(self, geo: GeoTool) -> None:
        assert geo.is_in_china(35.68, 139.69) is False


class TestIsInRegion:
    def test_point_in_province(self, geo: GeoTool) -> None:
        assert geo.is_in_region(39.9, 116.4, "110000") is True

    def test_point_in_city(self, geo: GeoTool) -> None:
        assert geo.is_in_region(22.55, 114.06, "440300") is True

    def test_point_in_district(self, geo: GeoTool) -> None:
        assert geo.is_in_region(32.06, 118.79, "320000") is True

    def test_point_not_in_district(self, geo: GeoTool) -> None:
        """Beijing point is NOT in Shenzhen."""
        assert geo.is_in_region(39.9, 116.4, "440300") is False

    def test_invalid_adcode(self, geo: GeoTool) -> None:
        with pytest.raises(ValueError):
            geo.is_in_region(39.9, 116.4, "xyz")

    def test_nonexistent_adcode(self, geo: GeoTool) -> None:
        with pytest.raises(ValueError):
            geo.is_in_region(39.9, 116.4, "999999")

    def test_agrees_with_reverse_on_hard_points(self, geo: GeoTool) -> None:
        """SPEC §2.9: is_in_region is reverse() compared at one level.

        加格达奇区 sits inside 内蒙古's province polygon but is administered
        by 黑龙江; a point in both 治多县 and 格尔木市's polygons belongs to
        whichever reverse() picks. Polygon containment gave the opposite
        answers for all of these.
        """
        for lat, lng in [(50.37295, 124.16537), (35.77829, 93.31087),
                         (30.66457, 122.56396), (30.21028, 105.65155)]:
            r = geo.reverse(lat, lng)
            for region in (r.province, r.city, r.district):
                if region is not None:
                    assert geo.is_in_region(lat, lng, region.code), (lat, lng, region)
        assert geo.is_in_region(50.37295, 124.16537, "230000")
        assert not geo.is_in_region(50.37295, 124.16537, "150000")
        assert geo.is_in_region(35.77829, 93.31087, "632724")
        assert not geo.is_in_region(35.77829, 93.31087, "632801")
