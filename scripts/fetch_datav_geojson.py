"""
Fetch administrative boundary GeoJSON from DataV GeoAtlas and convert to WGS-84.

DataV uses GCJ-02 coordinates. This script:
1. Recursively downloads province/city/district boundaries
2. Converts all coordinates from GCJ-02 to WGS-84
3. Outputs three GeoJSON files matching the existing project format
4. Generates china_admin.json from the same data source

Usage:
    python scripts/fetch_datav_geojson.py [--allow-partial] [--out DIR]

A run that loses any region — a 404, a rate limit that outlasts the retries,
a network drop half way — writes nothing and exits 1. The previous version
kept going and wrote every file with a zero exit status, so a city that
timed out simply lost its districts and the only trace was a "Removed"
list in DATA_UPDATE_REPORT.md that somebody had to read. --allow-partial
restores that behaviour for the case where the missing region really is
gone from the source.

Files are written to a temporary directory and moved into place together
at the end, so an interrupted run cannot leave GeoJSON from one fetch next
to an admin tree from another.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import math
import os
import shutil
import sys
import tempfile
import time
import urllib.error
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

class FetchError(Exception):
    """A region could not be fetched after the retries were exhausted."""


FAILURES: list[str] = []


def fetch_json(url: str) -> dict | None:
    """Fetch JSON, telling a missing resource apart from a failing service.

    404 means the source has no such region and is returned as None at once —
    retrying it is pointless and hides the difference from a real outage.
    429 and 5xx back off and retry; anything still failing after that is
    recorded in FAILURES, which decides whether the run may write at all.
    """
    delay = 2.0
    last_error: Exception | None = None
    for attempt in range(5):
        try:
            req = urllib.request.Request(url, headers={"User-Agent": "GeoToolCN-DataFetcher/1.0"})
            with urllib.request.urlopen(req, timeout=30) as resp:
                return json.loads(resp.read())
        except urllib.error.HTTPError as e:
            if e.code == 404:
                return None
            last_error = e
            if e.code == 429:
                retry_after = e.headers.get("Retry-After")
                delay = max(delay, float(retry_after)) if retry_after and retry_after.isdigit() else delay * 2
            elif 500 <= e.code < 600:
                delay *= 2
            else:
                break  # 401/403 and friends will not improve with retries
        except Exception as e:  # noqa: BLE001 - timeouts, DNS, resets
            last_error = e
            delay *= 2
        print(f"  Retry {attempt + 1}/5 for {url} in {delay:.0f}s: {last_error}")
        time.sleep(delay)
    print(f"  FAILED: {url}: {last_error}")
    FAILURES.append(f"{url}: {last_error}")
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


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__,
                                     formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--allow-partial", action="store_true",
                        help="write the files even if some regions could not be fetched")
    parser.add_argument("--out", type=Path, default=OUTPUT_DIR,
                        help=f"where to write (default: {OUTPUT_DIR})")
    args = parser.parse_args()
    out_dir = args.out

    print("Fetching national data...")
    national = fetch_region(100000)
    if not national:
        print("Failed to fetch national data, aborting.")
        return 1

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
            # Taiwan is the one province the source publishes without
            # children; anywhere else this is data loss.
            if str(adcode) != "710000":
                FAILURES.append(f"{name} ({adcode}): no children data")
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
                    if not district_data:
                        FAILURES.append(f"{child_name} ({child_adcode}): declares "
                                        f"{children_num} children, none fetched")
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

    # ── Refuse to write a partial dataset ────────────────────────────────
    if FAILURES:
        print(f"\n{len(FAILURES)} region(s) could not be fetched:")
        for f in FAILURES:
            print(f"  - {f}")
        if not args.allow_partial:
            print("\nNothing written. Re-run, or pass --allow-partial if the source "
                  "really no longer has these regions.")
            return 1
        print("\n--allow-partial: writing anyway.")

    # ── Load previous version for diff ─────────────────────────────────
    version_path = out_dir / "DATA_VERSION.json"
    old_version = None
    if version_path.exists():
        old_version = json.loads(version_path.read_text(encoding="utf-8"))

    old_admin = None
    admin_path = out_dir / "china_admin.json"
    if admin_path.exists():
        old_admin = json.loads(admin_path.read_text(encoding="utf-8"))

    # ── Write output files, atomically as a set ──────────────────────────
    out_dir.mkdir(parents=True, exist_ok=True)
    staging = Path(tempfile.mkdtemp(prefix="datav-", dir=out_dir))

    def write_geojson(filename: str, features: list):
        path = staging / filename
        geojson = {"type": "FeatureCollection", "features": features}
        path.write_text(json.dumps(geojson, ensure_ascii=False), encoding="utf-8")
        print(f"\nStaged {filename} ({len(features)} features)")

    write_geojson("china_province.geojson", provinces)
    write_geojson("china_city.geojson", cities)
    write_geojson("china_district.geojson", districts)

    admin_text = json.dumps(admin_tree, ensure_ascii=False, indent=2)
    (staging / "china_admin.json").write_text(admin_text, encoding="utf-8")
    print(f"Staged china_admin.json")
    print(f"  provinces: {len(admin_tree['provinces'])}")
    print(f"  cities: {len(admin_tree['cities'])}")
    print(f"  districts: {len(admin_tree['districts'])}")

    # ── DATA_VERSION.json ────────────────────────────────────────────────
    new_counts = {
        "provinces": len(provinces),
        "cities": len(cities),
        "districts": len(districts),
    }
    # The identity of a dataset is its content, not the day it was fetched:
    # the same DataV snapshot fetched a day later must not look like a new
    # version. The admin tree covers every code and name, so its hash is the
    # version; fetched_at stays for humans.
    content_hash = hashlib.sha256(admin_text.encode("utf-8")).hexdigest()
    new_version = {
        "source": "DataV.GeoAtlas (阿里云 DataV 地理小工具)",
        "source_url": "https://datav.aliyun.com/tools/atlas",
        "api_base": BASE_URL,
        "fetched_at": date.today().isoformat(),
        "content_sha256": content_hash,
        "original_crs": "GCJ-02",
        "converted_crs": "WGS-84",
        "conversion": {
            "method": "single-step inverse of the GCJ-02 offset, per vertex",
            "residual_m": "0.6 median, up to ~5 at the edges of the covered area",
            "note": "Every vertex carries this systematic residual on top of the "
                    "source's own accuracy; sub-metre boundary decisions are noise.",
        },
        "license": {
            "code": "MIT (this repository)",
            "data": "DataV.GeoAtlas: 数据来源于高德开放平台，仅供学习交流使用 (learning and exchange only; see NOTICE)",
        },
        "source_notice": "数据来源于高德开放平台，仅供学习交流使用，若有版权相关问题，请前往高德开放平台确认",
        "counts": new_counts,
        "notes": "Taiwan (710000) has province-level boundary only, no sub-level data.",
    }
    (staging / "DATA_VERSION.json").write_text(
        json.dumps(new_version, ensure_ascii=False, indent=2), encoding="utf-8"
    )

    # ── Diff report ──────────────────────────────────────────────────────
    report = _build_diff_report(old_version, old_admin, new_version, admin_tree)
    # The report lives at the repository root next to the CHANGELOG; a custom
    # --out keeps everything, report included, in that directory.
    repo_root = Path(__file__).resolve().parent.parent
    report_path = (repo_root if out_dir == OUTPUT_DIR else out_dir) / "DATA_UPDATE_REPORT.md"

    # Everything staged; now move the set into place. os.replace is atomic
    # per file, and the files are small enough that the window between them
    # is milliseconds rather than the minutes the fetch took.
    for name in ("china_province.geojson", "china_city.geojson", "china_district.geojson",
                 "china_admin.json", "DATA_VERSION.json"):
        os.replace(staging / name, out_dir / name)
        print(f"Wrote {out_dir / name}")
    shutil.rmtree(staging, ignore_errors=True)
    report_path.write_text(report, encoding="utf-8")
    print(f"Wrote {report_path}")

    # ── Run validation ───────────────────────────────────────────────
    print("\n" + "=" * 60)
    print("Running post-update validation...")
    print("=" * 60 + "\n")
    sys.path.insert(0, str(Path(__file__).resolve().parent))
    from validate_data import validate as run_validation  # noqa: PLC0415

    errors = run_validation(out_dir)
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
        print("Review the errors above before committing.")
        return 1
    print(f"\nValidation PASSED ({len(warns)} warning(s)).")
    print("\nNext: python pipeline/build_gtc.py && python scripts/validate_gtc.py --round-trip"
          " && python conformance/generate.py && bash packages/go/scripts/sync-data.sh")
    return 0


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
        # Keyed by code, so a renamed division shows as a rename rather than
        # as one removal plus one addition — a consumer keying stored results
        # by adcode needs to know which codes vanished, not which names did.
        for key, label in [("provinces", "Provinces"), ("cities", "Cities"), ("districts", "Districts")]:
            old_by_code = {code: name for code, name in old_admin.get(key, [])}
            new_by_code = {code: name for code, name in new_admin[key]}
            added = sorted(c for c in new_by_code if c not in old_by_code)
            removed = sorted(c for c in old_by_code if c not in new_by_code)
            renamed = sorted(c for c in new_by_code if c in old_by_code and old_by_code[c] != new_by_code[c])
            if added or removed or renamed:
                lines.append(f"### {label}")
                lines.append("")
                if added:
                    lines.append(f"**Added ({len(added)})** — new codes; nothing stored refers to them yet:")
                    for code in added:
                        lines.append(f"- `{code}` {new_by_code[code]}")
                    lines.append("")
                if removed:
                    lines.append(f"**Removed ({len(removed)})** — codes that no longer resolve; "
                                 f"stored results keyed by these need remapping:")
                    for code in removed:
                        lines.append(f"- `{code}` {old_by_code[code]}")
                    lines.append("")
                if renamed:
                    lines.append(f"**Renamed ({len(renamed)})** — same code, new name:")
                    for code in renamed:
                        lines.append(f"- `{code}` {old_by_code[code]} → {new_by_code[code]}")
                    lines.append("")

    if not old_admin and not old_ver:
        lines += ["", "*First import — no previous data to compare.*"]

    lines.append("")
    return "\n".join(lines)


if __name__ == "__main__":
    sys.exit(main())
