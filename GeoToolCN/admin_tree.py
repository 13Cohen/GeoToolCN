"""Administrative region tree builder.

Builds a three-level (province → city → district) tree from the bundled
``china_admin.json`` data.  This module uses **only the standard library**
and does not import geopandas, pandas, or shapely.

Data source: DataV.GeoAtlas (阿里云 DataV 地理小工具)
https://datav.aliyun.com/tools/atlas
"""
from __future__ import annotations

import json
import os
from typing import Any

from ._hierarchy import MERGED_PREFIXES, parent_city_code

_DATA_PATH = os.path.join(os.path.dirname(__file__), "data", "china_admin.json")

_cached_tree: list[dict[str, Any]] | None = None


def _build_tree() -> list[dict[str, Any]]:
    with open(_DATA_PATH, encoding="utf-8") as f:
        raw = json.load(f)

    provinces = {code: name for code, name in raw["provinces"]}
    cities_by_2 = _group_by_prefix(raw["cities"], 2)

    # Attach each district to the city the hierarchy rules name as its parent.
    # Grouping by 4-digit prefix instead would place every province-directly-
    # governed county-level division under all of its siblings, since they
    # share one prefix — 海南's 15 such cities each listed the other 14.
    city_codes = {code for code, _ in raw["cities"]}
    dists_by_parent: dict[str, list[tuple[str, str]]] = {}
    for code, name in raw["districts"]:
        parent = parent_city_code(code, city_codes)
        if parent is not None:
            dists_by_parent.setdefault(parent, []).append((code, name))

    tree: list[dict[str, Any]] = []

    for prov_code in sorted(provinces):
        prefix2 = prov_code[:2]
        prov_node: dict[str, Any] = {
            "value": prov_code,
            "label": provinces[prov_code],
            "children": [],
        }

        if prefix2 in MERGED_PREFIXES:
            # Municipality / SAR: single city node, value = province code
            city_node: dict[str, Any] = {
                "value": prov_code,
                "label": provinces[prov_code],
                "children": [
                    {"value": code, "label": name}
                    for code, name in sorted(dists_by_parent.get(prov_code, []))
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
                        for code, name in sorted(dists_by_parent.get(city_code, []))
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
