"""Administrative region tree builder.

Builds a three-level (province → city → district) tree from the bundled
``china_admin.json`` data.  This module uses **only the standard library**
and does not import geopandas, pandas, or shapely.

Data source: 腾讯位置服务 行政区划编码表
https://lbs.qq.com/service/webService/webServiceGuide/search/webServiceDistrict
"""
from __future__ import annotations

import json
import os
from typing import Any

_DATA_PATH = os.path.join(os.path.dirname(__file__), "data", "china_admin.json")

# Municipalities (直辖市) and SARs (特别行政区):
# Their city-level node uses the province code as its value.
_MERGED_PREFIXES = frozenset({"11", "12", "31", "50", "81", "82"})

_cached_tree: list[dict[str, Any]] | None = None


def _build_tree() -> list[dict[str, Any]]:
    with open(_DATA_PATH, encoding="utf-8") as f:
        raw = json.load(f)

    provinces = {code: name for code, name in raw["provinces"]}
    cities_by_2 = _group_by_prefix(raw["cities"], 2)
    dists_by_2 = _group_by_prefix(raw["districts"], 2)
    dists_by_4 = _group_by_prefix(raw["districts"], 4)

    tree: list[dict[str, Any]] = []

    for prov_code in sorted(provinces):
        prefix2 = prov_code[:2]
        prov_node: dict[str, Any] = {
            "value": prov_code,
            "label": provinces[prov_code],
            "children": [],
        }

        if prefix2 in _MERGED_PREFIXES:
            # Municipality / SAR: single city node, value = province code
            city_node: dict[str, Any] = {
                "value": prov_code,
                "label": provinces[prov_code],
                "children": [
                    {"value": code, "label": name}
                    for code, name in sorted(dists_by_2.get(prefix2, []))
                ],
            }
            prov_node["children"].append(city_node)
        else:
            # Normal province: match cities, then districts under each city
            for city_code, city_name in sorted(cities_by_2.get(prefix2, [])):
                city_node = {
                    "value": city_code,
                    "label": city_name,
                    "children": [
                        {"value": code, "label": name}
                        for code, name in sorted(
                            dists_by_4.get(city_code[:4], [])
                        )
                    ],
                }
                prov_node["children"].append(city_node)

        tree.append(prov_node)

    return tree


def _group_by_prefix(
    pairs: list[list[str]], length: int
) -> dict[str, list[tuple[str, str]]]:
    """Group ``[code, name]`` pairs by the first *length* chars of code."""
    groups: dict[str, list[tuple[str, str]]] = {}
    for code, name in pairs:
        groups.setdefault(code[:length], []).append((code, name))
    return groups


def get_administrative_tree() -> list[dict[str, Any]]:
    """Return a three-level administrative-region tree.

    Each node has the shape::

        {"value": "<6-digit adcode>", "label": "<name>", "children": [...]}

    The tree is **province → city → district**, sorted by ``value`` at
    every level.  The result is cached after the first call.

    Municipalities (北京, 天津, 上海, 重庆) and SARs (香港, 澳门) each
    have a single city-level node whose ``value`` equals the province code.

    Returns
    -------
    list[dict]
        One dict per provincial-level unit (34 total including Taiwan,
        Hong Kong, and Macau).
    """
    global _cached_tree
    if _cached_tree is None:
        _cached_tree = _build_tree()
    return _cached_tree
