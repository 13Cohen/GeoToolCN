"""
Fetch administrative boundary GeoJSON from DataV GeoAtlas and convert to WGS-84.

DataV uses GCJ-02 coordinates. This script:
1. Recursively downloads province/city/district boundaries
2. Converts all coordinates from GCJ-02 to WGS-84
3. Outputs three GeoJSON files matching the existing project format
4. Generates china_admin.json from the same data source

Usage:
    python scripts/fetch_datav_geojson.py
"""

from __future__ import annotations

import json
import math
import time
import urllib.request
from datetime import date
from pathlib import Path

BASE_URL = "https://geo.datav.aliyun.com/areas_v3/bound"
OUTPUT_DIR = Path(__file__).resolve().parent.parent / "GeoToolCN" / "data"
REQUEST_DELAY = 0.3  # seconds between requests to be polite


# ── GCJ-02 → WGS-84 conversion ──────────────────────────────────────────────

_A = 6378245.0
_EE = 0.00669342162296594323


def _transform_lat(x: float, y: float) -> float:
    ret = -100.0 + 2.0 * x + 3.0 * y + 0.2 * y * y + 0.1 * x * y + 0.2 * math.sqrt(abs(x))
    ret += (20.0 * math.sin(6.0 * x * math.pi) + 20.0 * math.sin(2.0 * x * math.pi)) * 2.0 / 3.0
    ret += (20.0 * math.sin(y * math.pi) + 40.0 * math.sin(y / 3.0 * math.pi)) * 2.0 / 3.0
    ret += (160.0 * math.sin(y / 12.0 * math.pi) + 320.0 * math.sin(y * math.pi / 30.0)) * 2.0 / 3.0
    return ret


def _transform_lng(x: float, y: float) -> float:
    ret = 300.0 + x + 2.0 * y + 0.1 * x * x + 0.1 * x * y + 0.1 * math.sqrt(abs(x))
    ret += (20.0 * math.sin(6.0 * x * math.pi) + 20.0 * math.sin(2.0 * x * math.pi)) * 2.0 / 3.0
    ret += (20.0 * math.sin(x * math.pi) + 40.0 * math.sin(x / 3.0 * math.pi)) * 2.0 / 3.0
    ret += (150.0 * math.sin(x / 12.0 * math.pi) + 300.0 * math.sin(x / 30.0 * math.pi)) * 2.0 / 3.0
    return ret


def gcj02_to_wgs84(lng: float, lat: float) -> tuple[float, float]:
    """Convert a single GCJ-02 coordinate to WGS-84."""
    d_lat = _transform_lat(lng - 105.0, lat - 35.0)
    d_lng = _transform_lng(lng - 105.0, lat - 35.0)
    rad_lat = lat / 180.0 * math.pi
    magic = math.sin(rad_lat)
    magic = 1 - _EE * magic * magic
    sqrt_magic = math.sqrt(magic)
    d_lat = (d_lat * 180.0) / ((_A * (1 - _EE)) / (magic * sqrt_magic) * math.pi)
    d_lng = (d_lng * 180.0) / (_A / sqrt_magic * math.cos(rad_lat) * math.pi)
    return round(lng - d_lng, 6), round(lat - d_lat, 6)


def convert_coords(coords):
    """Recursively convert all coordinate pairs in a GeoJSON geometry."""
    if isinstance(coords[0], (int, float)):
        return list(gcj02_to_wgs84(coords[0], coords[1]))
    return [convert_coords(c) for c in coords]


def convert_feature(feature: dict) -> dict:
    """Convert a feature's geometry coordinates from GCJ-02 to WGS-84."""
    feature = json.loads(json.dumps(feature))  # deep copy
    geom = feature["geometry"]
    if geom and geom.get("coordinates"):
        geom["coordinates"] = convert_coords(geom["coordinates"])
    # Also convert center/centroid in properties
    props = feature["properties"]
    for key in ("center", "centroid"):
        if props.get(key):
            props[key] = list(gcj02_to_wgs84(props[key][0], props[key][1]))
    return feature


# ── HTTP fetch ───────────────────────────────────────────────────────────────

def fetch_json(url: str) -> dict | None:
    """Fetch JSON from URL with retry."""
    for attempt in range(3):
        try:
            req = urllib.request.Request(url, headers={"User-Agent": "GeoToolCN-DataFetcher/1.0"})
            with urllib.request.urlopen(req, timeout=30) as resp:
                return json.loads(resp.read())
        except Exception as e:
            print(f"  Retry {attempt + 1}/3 for {url}: {e}")
            time.sleep(2)
    print(f"  FAILED: {url}")
    return None


def fetch_region(adcode: int) -> dict | None:
    """Fetch the _full.json for a region."""
    url = f"{BASE_URL}/{adcode}_full.json"
    data = fetch_json(url)
    time.sleep(REQUEST_DELAY)
    return data


def fetch_boundary(adcode: int) -> dict | None:
    """Fetch the boundary-only .json for a region (no children)."""
    url = f"{BASE_URL}/{adcode}.json"
    data = fetch_json(url)
    time.sleep(REQUEST_DELAY)
    return data


# ── Main logic ───────────────────────────────────────────────────────────────

def normalize_properties(props: dict, level: str) -> dict:
    """Convert DataV properties to our project format: name + adcode."""
    return {
        "name": props["name"],
        "adcode": str(props["adcode"]),
        "center": props.get("center"),
        "centroid": props.get("centroid"),
        "level": level,
        "childrenNum": props.get("childrenNum", 0),
    }


def main():
    print("Fetching national data...")
    national = fetch_region(100000)
    if not national:
        print("Failed to fetch national data, aborting.")
        return

    provinces = []
    cities = []
    districts = []
    admin_tree = {"provinces": [], "cities": [], "districts": []}

    for feat in national["features"]:
        props = feat["properties"]
        adcode = props["adcode"]
        name = props["name"]
        level = props.get("level")

        if level != "province":
            continue

        print(f"\n[Province] {name} ({adcode})")

        # Store province feature
        converted = convert_feature(feat)
        converted["properties"] = normalize_properties(props, "province")
        # Re-apply converted center/centroid
        for key in ("center", "centroid"):
            if props.get(key):
                converted["properties"][key] = list(gcj02_to_wgs84(props[key][0], props[key][1]))
        provinces.append(converted)
        admin_tree["provinces"].append([str(adcode), name])

        # Fetch children (cities/districts)
        children_data = fetch_region(adcode)
        if not children_data:
            print(f"  No children data for {name}")
            continue

        for child_feat in children_data["features"]:
            child_props = child_feat["properties"]
            child_adcode = child_props["adcode"]
            child_name = child_props["name"]
            child_level = child_props.get("level", "district")
            children_num = child_props.get("childrenNum", 0)

            converted_child = convert_feature(child_feat)
            converted_child["properties"] = normalize_properties(child_props, child_level)
            for key in ("center", "centroid"):
                if child_props.get(key):
                    converted_child["properties"][key] = list(
                        gcj02_to_wgs84(child_props[key][0], child_props[key][1])
                    )

            if child_level == "city":
                print(f"  [City] {child_name} ({child_adcode}) children={children_num}")
                cities.append(converted_child)
                admin_tree["cities"].append([str(child_adcode), child_name])

                # Fetch district children
                if children_num > 0:
                    district_data = fetch_region(child_adcode)
                    if district_data:
                        for dist_feat in district_data["features"]:
                            dist_props = dist_feat["properties"]
                            dist_adcode = dist_props["adcode"]
                            dist_name = dist_props["name"]
                            print(f"    [District] {dist_name} ({dist_adcode})")

                            converted_dist = convert_feature(dist_feat)
                            converted_dist["properties"] = normalize_properties(dist_props, "district")
                            for key in ("center", "centroid"):
                                if dist_props.get(key):
                                    converted_dist["properties"][key] = list(
                                        gcj02_to_wgs84(dist_props[key][0], dist_props[key][1])
                                    )
                            districts.append(converted_dist)
                            admin_tree["districts"].append([str(dist_adcode), dist_name])
                else:
                    # City with no children (e.g. 儋州市, 兵团城市)
                    # Treat itself as both city and district
                    districts.append(json.loads(json.dumps(converted_child)))
                    districts[-1]["properties"]["level"] = "district"
                    admin_tree["districts"].append([str(child_adcode), child_name])
            else:
                # Direct district under province (e.g. Beijing's districts)
                print(f"  [District] {child_name} ({child_adcode})")
                districts.append(converted_child)
                admin_tree["districts"].append([str(child_adcode), child_name])

    # ── Load previous version for diff ─────────────────────────────────
    version_path = OUTPUT_DIR / "DATA_VERSION.json"
    old_version = None
    if version_path.exists():
        old_version = json.loads(version_path.read_text(encoding="utf-8"))

    old_admin = None
    admin_path = OUTPUT_DIR / "china_admin.json"
    if admin_path.exists():
        old_admin = json.loads(admin_path.read_text(encoding="utf-8"))

    # ── Write output files ───────────────────────────────────────────────
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)

    def write_geojson(filename: str, features: list):
        path = OUTPUT_DIR / filename
        geojson = {"type": "FeatureCollection", "features": features}
        path.write_text(json.dumps(geojson, ensure_ascii=False), encoding="utf-8")
        print(f"\nWrote {path} ({len(features)} features)")

    write_geojson("china_province.geojson", provinces)
    write_geojson("china_city.geojson", cities)
    write_geojson("china_district.geojson", districts)

    # Write admin tree
    admin_path.write_text(json.dumps(admin_tree, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"Wrote {admin_path}")
    print(f"  provinces: {len(admin_tree['provinces'])}")
    print(f"  cities: {len(admin_tree['cities'])}")
    print(f"  districts: {len(admin_tree['districts'])}")

    # ── Write DATA_VERSION.json ──────────────────────────────────────────
    new_counts = {
        "provinces": len(provinces),
        "cities": len(cities),
        "districts": len(districts),
    }
    new_version = {
        "source": "DataV.GeoAtlas (阿里云 DataV 地理小工具)",
        "source_url": "https://datav.aliyun.com/tools/atlas",
        "api_base": BASE_URL,
        "fetched_at": date.today().isoformat(),
        "original_crs": "GCJ-02",
        "converted_crs": "WGS-84",
        "counts": new_counts,
        "notes": "Taiwan (710000) has province-level boundary only, no sub-level data.",
    }
    version_path.write_text(
        json.dumps(new_version, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    print(f"\nWrote {version_path}")

    # ── Generate diff report ─────────────────────────────────────────────
    report = _build_diff_report(old_version, old_admin, new_version, admin_tree)
    report_path = OUTPUT_DIR.parent.parent / "DATA_UPDATE_REPORT.md"
    report_path.write_text(report, encoding="utf-8")
    print(f"Wrote {report_path}")

    # ── Run validation ───────────────────────────────────────────────
    print("\n" + "=" * 60)
    print("Running post-update validation...")
    print("=" * 60 + "\n")
    from validate_data import validate as run_validation

    errors = run_validation()
    warns = [e for e in errors if e.severity == "WARN"]
    errs = [e for e in errors if e.severity == "ERROR"]

    if warns:
        print(f"\nWarnings ({len(warns)}):")
        for w in warns:
            print(f"  {w}")

    if errs:
        print(f"\nERRORS ({len(errs)}):")
        for e in errs:
            print(f"  {e}")
        print(f"\nData update completed but validation FAILED with {len(errs)} error(s).")
        print("Review the errors above before publishing.")
    else:
        print(f"\nValidation PASSED ({len(warns)} warning(s)).")

    print("\nDone!")


def _build_diff_report(
    old_ver: dict | None,
    old_admin: dict | None,
    new_ver: dict,
    new_admin: dict,
) -> str:
    """Build a markdown report comparing old and new data."""
    lines = [
        "# Data Update Report",
        "",
        f"**Date**: {new_ver['fetched_at']}",
        f"**Source**: [{new_ver['source']}]({new_ver['source_url']})",
        f"**CRS**: {new_ver['original_crs']} → {new_ver['converted_crs']}",
        "",
    ]

    new_c = new_ver["counts"]

    if old_ver is None:
        lines += [
            "## Initial Import",
            "",
            f"| Level | Count |",
            f"|-------|-------|",
            f"| Provinces | {new_c['provinces']} |",
            f"| Cities | {new_c['cities']} |",
            f"| Districts | {new_c['districts']} |",
        ]
    else:
        old_c = old_ver.get("counts", {})
        lines += [
            f"**Previous fetch**: {old_ver.get('fetched_at', 'unknown')}",
            "",
            "## Count Changes",
            "",
            "| Level | Before | After | Diff |",
            "|-------|--------|-------|------|",
        ]
        for key, label in [("provinces", "Provinces"), ("cities", "Cities"), ("districts", "Districts")]:
            before = old_c.get(key, 0)
            after = new_c[key]
            diff = after - before
            diff_str = f"+{diff}" if diff > 0 else str(diff) if diff != 0 else "—"
            lines.append(f"| {label} | {before} | {after} | {diff_str} |")

    if old_admin is not None:
        lines += ["", "## Detail Changes", ""]
        for key, label in [("provinces", "Provinces"), ("cities", "Cities"), ("districts", "Districts")]:
            old_set = {tuple(x) for x in old_admin.get(key, [])}
            new_set = {tuple(x) for x in new_admin[key]}
            added = sorted(new_set - old_set)
            removed = sorted(old_set - new_set)
            if added or removed:
                lines.append(f"### {label}")
                lines.append("")
                if added:
                    lines.append(f"**Added ({len(added)})**:")
                    for code, name in added:
                        lines.append(f"- `{code}` {name}")
                    lines.append("")
                if removed:
                    lines.append(f"**Removed ({len(removed)})**:")
                    for code, name in removed:
                        lines.append(f"- `{code}` {name}")
                    lines.append("")

    if not old_admin and not old_ver:
        lines += ["", "*First import — no previous data to compare.*"]

    lines.append("")
    return "\n".join(lines)


if __name__ == "__main__":
    main()
