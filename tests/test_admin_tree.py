"""Tests for get_administrative_tree()."""
from __future__ import annotations

import pytest

from GeoToolCN import get_administrative_tree


@pytest.fixture(scope="module")
def tree() -> list[dict]:
    return get_administrative_tree()


def _find(nodes: list[dict], value: str) -> dict:
    """Find a node by value in a list."""
    return next(n for n in nodes if n["value"] == value)


# ---------------------------------------------------------------
# Tree structure
# ---------------------------------------------------------------


class TestTreeStructure:
    def test_returns_list(self, tree: list[dict]) -> None:
        assert isinstance(tree, list)

    def test_province_count(self, tree: list[dict]) -> None:
        assert len(tree) == 34

    def test_sorted_by_value(self, tree: list[dict]) -> None:
        values = [n["value"] for n in tree]
        assert values == sorted(values)

    def test_node_shape(self, tree: list[dict]) -> None:
        node = tree[0]
        assert set(node.keys()) >= {"value", "label", "children"}

    def test_every_province_has_children(self, tree: list[dict]) -> None:
        for prov in tree:
            assert len(prov["children"]) > 0, f"{prov['label']} has no children"

    def test_city_children_sorted(self, tree: list[dict]) -> None:
        for prov in tree:
            city_values = [c["value"] for c in prov["children"]]
            assert city_values == sorted(city_values), (
                f"{prov['label']} cities not sorted"
            )

    def test_district_children_sorted(self, tree: list[dict]) -> None:
        for prov in tree:
            for city in prov["children"]:
                dist_values = [d["value"] for d in city.get("children", [])]
                assert dist_values == sorted(dist_values), (
                    f"{city['label']} districts not sorted"
                )


# ---------------------------------------------------------------
# Municipalities (直辖市)
# ---------------------------------------------------------------


class TestMunicipalities:
    def test_beijing_single_city(self, tree: list[dict]) -> None:
        bj = _find(tree, "110000")
        assert len(bj["children"]) == 1

    def test_beijing_city_value_equals_province(self, tree: list[dict]) -> None:
        bj = _find(tree, "110000")
        assert bj["children"][0]["value"] == "110000"

    def test_beijing_districts(self, tree: list[dict]) -> None:
        bj = _find(tree, "110000")
        districts = bj["children"][0]["children"]
        assert len(districts) == 16
        names = {d["label"] for d in districts}
        assert "朝阳区" in names
        assert "海淀区" in names

    def test_shanghai_city_value_equals_province(self, tree: list[dict]) -> None:
        sh = _find(tree, "310000")
        assert sh["children"][0]["value"] == "310000"

    def test_chongqing_city_value_equals_province(self, tree: list[dict]) -> None:
        cq = _find(tree, "500000")
        assert cq["children"][0]["value"] == "500000"


# ---------------------------------------------------------------
# SARs (特别行政区)
# ---------------------------------------------------------------


class TestSAR:
    def test_hk_province_and_city_value(self, tree: list[dict]) -> None:
        hk = _find(tree, "810000")
        assert hk["label"] == "香港特别行政区"
        assert hk["children"][0]["value"] == "810000"

    def test_hk_18_districts(self, tree: list[dict]) -> None:
        hk = _find(tree, "810000")
        districts = hk["children"][0]["children"]
        assert len(districts) == 18

    def test_macau_province_and_city_value(self, tree: list[dict]) -> None:
        mac = _find(tree, "820000")
        assert mac["label"] == "澳门特别行政区"
        assert mac["children"][0]["value"] == "820000"

    def test_macau_3_districts(self, tree: list[dict]) -> None:
        mac = _find(tree, "820000")
        districts = mac["children"][0]["children"]
        assert len(districts) == 3
        names = {d["label"] for d in districts}
        assert "澳门半岛" in names


# ---------------------------------------------------------------
# Taiwan
# ---------------------------------------------------------------


class TestTaiwan:
    def test_taiwan_exists(self, tree: list[dict]) -> None:
        tw = _find(tree, "710000")
        assert tw["label"] == "台湾省"

    def test_taiwan_20_cities(self, tree: list[dict]) -> None:
        tw = _find(tree, "710000")
        assert len(tw["children"]) == 20

    def test_taipei_districts(self, tree: list[dict]) -> None:
        tw = _find(tree, "710000")
        taipei = _find(tw["children"], "711000")
        assert taipei["label"] == "台北市"
        assert len(taipei["children"]) == 12


# ---------------------------------------------------------------
# Normal province
# ---------------------------------------------------------------


class TestNormalProvince:
    def test_guangdong_cities(self, tree: list[dict]) -> None:
        gd = _find(tree, "440000")
        assert len(gd["children"]) == 21

    def test_shenzhen_districts(self, tree: list[dict]) -> None:
        gd = _find(tree, "440000")
        sz = _find(gd["children"], "440300")
        assert len(sz["children"]) == 9
        names = {d["label"] for d in sz["children"]}
        assert "南山区" in names


# ---------------------------------------------------------------
# Caching
# ---------------------------------------------------------------


class TestCaching:
    def test_same_object_returned(self) -> None:
        tree1 = get_administrative_tree()
        tree2 = get_administrative_tree()
        assert tree1 is tree2
