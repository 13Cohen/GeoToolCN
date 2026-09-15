"""
Validate GeoToolCN data files after a data update.

Checks:
1. File existence and loadability
2. Count sanity (provinces ~34, cities 300-400, districts 2500-3500)
3. Adcode format (6 digits, no duplicates)
4. Parent-child adcode prefix consistency
5. Geometry validity (no empty/null geometries)
6. Known landmark spot checks — point-in-polygon against the *new* province
   GeoJSON (this used to load the previously built .gtc, i.e. the old data)
7. Admin tree ↔ GeoJSON consistency, at every level
8. Every non-Taiwan province has districts; every city that declares
   children has districts under its prefix
9. Every vertex lies inside the China bounding box

Usage:
    python scripts/validate_data.py
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

_PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(_PROJECT_ROOT))

DATA_DIR = _PROJECT_ROOT / "GeoToolCN" / "data"

# Expected count ranges (loose bounds to catch catastrophic errors)
COUNT_BOUNDS = {
    "provinces": (30, 40),
    "cities": (300, 420),
    "districts": (2500, 3500),
}

# Known landmarks: (lat, lng, expected_province_adcode_prefix)
LANDMARKS = [
    (39.9042, 116.4074, "11", "Beijing"),
    (31.2304, 121.4737, "31", "Shanghai"),
    (23.1291, 113.2644, "44", "Guangdong"),
    (30.5728, 104.0668, "51", "Sichuan"),
    (29.5630, 106.5516, "50", "Chongqing"),
    (45.7500, 126.6500, "23", "Heilongjiang"),
    (36.0671, 120.3826, "37", "Shandong"),
    (25.0389, 102.7183, "53", "Yunnan"),
]

# Municipalities / SARs that have no city-level GeoJSON
MERGED_PREFIXES = {"11", "12", "31", "50", "81", "82"}


class ValidationError:
    def __init__(self, category: str, message: str, severity: str = "ERROR"):
        self.category = category
        self.message = message
        self.severity = severity  # ERROR or WARN

    def __str__(self):
        return f"[{self.severity}] {self.category}: {self.message}"


# Every vertex of every polygon must fall in here; a file that was converted
# twice, or not at all, still would, so this is a gross-error check only —
# the landmark checks below are what catch a wrong CRS.
CHINA_BBOX = (72.0, 0.5, 138.0, 56.0)  # lng_min, lat_min, lng_max, lat_max


def validate(data_dir: Path = DATA_DIR) -> list[ValidationError]:
    errors: list[ValidationError] = []
    DATA_DIR_ = data_dir

    # ── 1. File existence ─────────────────────────────────────────────
    required_files = [
        "china_province.geojson",
        "china_city.geojson",
        "china_district.geojson",
        "china_admin.json",
        "DATA_VERSION.json",
    ]
    for fname in required_files:
        if not (DATA_DIR_ / fname).exists():
            errors.append(ValidationError("FILE", f"Missing required file: {fname}"))

    if any(e.category == "FILE" for e in errors):
        return errors  # Can't continue without files

    # ── 2. Load GeoJSON files ─────────────────────────────────────────
    geojsons = {}
    for level in ("province", "city", "district"):
        path = DATA_DIR_ / f"china_{level}.geojson"
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
            geojsons[level] = data["features"]
        except Exception as e:
            errors.append(ValidationError("LOAD", f"Failed to load {path.name}: {e}"))
            return errors

    # ── 3. Count sanity ───────────────────────────────────────────────
    level_keys = {"province": "provinces", "city": "cities", "district": "districts"}
    for level, features in geojsons.items():
        count = len(features)
        key = level_keys[level]
        lo, hi = COUNT_BOUNDS[key]
        if not (lo <= count <= hi):
            errors.append(ValidationError(
                "COUNT",
                f"{key} count {count} outside expected range [{lo}, {hi}]",
            ))

    # ── 4. Adcode format & duplicates ─────────────────────────────────
    for level, features in geojsons.items():
        seen: dict[str, str] = {}
        for feat in features:
            props = feat.get("properties", {})
            adcode = str(props.get("adcode", ""))
            name = props.get("name", "?")

            if not adcode.isdigit() or len(adcode) != 6:
                errors.append(ValidationError(
                    "ADCODE", f"Invalid adcode {adcode!r} for {name} at {level} level"
                ))
                continue

            if adcode in seen:
                errors.append(ValidationError(
                    "ADCODE",
                    f"Duplicate adcode {adcode} in {level}: "
                    f"{seen[adcode]!r} and {name!r}",
                ))
            seen[adcode] = name

    # ── 5. Parent-child prefix consistency ────────────────────────────
    province_prefixes = {
        str(f["properties"]["adcode"])[:2]
        for f in geojsons["province"]
    }

    for feat in geojsons["city"]:
        adcode = str(feat["properties"]["adcode"])
        prefix2 = adcode[:2]
        if prefix2 not in province_prefixes:
            errors.append(ValidationError(
                "HIERARCHY",
                f"City {feat['properties']['name']} ({adcode}) has no "
                f"matching province for prefix {prefix2}",
            ))

    city_codes = {str(f["properties"]["adcode"]) for f in geojsons["city"]}
    city_prefixes = {c[:4] for c in city_codes}
    for feat in geojsons["district"]:
        adcode = str(feat["properties"]["adcode"])
        prefix2 = adcode[:2]
        prefix4 = adcode[:4]
        if prefix2 in MERGED_PREFIXES:
            # Districts under municipalities sit directly under province
            if prefix2 not in province_prefixes:
                errors.append(ValidationError(
                    "HIERARCHY",
                    f"District {feat['properties']['name']} ({adcode}) "
                    f"under municipality prefix {prefix2} has no province",
                ))
        elif prefix4 not in city_prefixes and adcode not in city_codes:
            # The 30 province-governed county-level divisions (4190/4290/
            # 4690/6590) have no prefix-4 city and are published in the city
            # layer under their own code; anything else without a parent is
            # a real gap, so this is an error rather than the warning that
            # used to fire for all 30 of them and drown everything else.
            errors.append(ValidationError(
                "HIERARCHY",
                f"District {feat['properties']['name']} ({adcode}) has no "
                f"matching city for prefix {prefix4} and is not a city itself",
            ))

    # A city that says it has children must have districts under it; a
    # fetch that timed out on one city loses exactly those and nothing else
    # in the counts notices.
    district_prefixes = {str(f["properties"]["adcode"])[:4] for f in geojsons["district"]}
    for feat in geojsons["city"]:
        props = feat["properties"]
        adcode = str(props["adcode"])
        if props.get("childrenNum", 0) > 0 and adcode[:4] not in district_prefixes:
            errors.append(ValidationError(
                "HIERARCHY",
                f"City {props['name']} ({adcode}) declares {props['childrenNum']} "
                f"children but the district layer has none under {adcode[:4]}",
            ))

    # ── 6. Geometry checks ────────────────────────────────────────────
    for level, features in geojsons.items():
        for feat in features:
            geom = feat.get("geometry")
            name = feat.get("properties", {}).get("name", "?")
            adcode = feat.get("properties", {}).get("adcode", "?")
            if geom is None:
                errors.append(ValidationError(
                    "GEOMETRY", f"Null geometry for {name} ({adcode}) at {level}"
                ))
            elif not geom.get("coordinates"):
                errors.append(ValidationError(
                    "GEOMETRY", f"Empty coordinates for {name} ({adcode}) at {level}"
                ))

    # ── 6b. Every vertex inside the China bounding box ───────────────
    def vertices(coords):
        if isinstance(coords[0], (int, float)):
            yield coords
        else:
            for c in coords:
                yield from vertices(c)

    lng_min, lat_min, lng_max, lat_max = CHINA_BBOX
    for level, features in geojsons.items():
        for feat in features:
            geom = feat.get("geometry") or {}
            if not geom.get("coordinates"):
                continue
            bad = next((v for v in vertices(geom["coordinates"])
                        if not (lng_min <= v[0] <= lng_max and lat_min <= v[1] <= lat_max)), None)
            if bad is not None:
                props = feat.get("properties", {})
                errors.append(ValidationError(
                    "GEOMETRY",
                    f"{props.get('name')} ({props.get('adcode')}) at {level} has a vertex "
                    f"outside China's bounding box: {bad[:2]} — wrong CRS or a swapped axis?",
                ))

    # ── 7. Province coverage ──────────────────────────────────────────
    district_prov_prefixes = {
        str(f["properties"]["adcode"])[:2] for f in geojsons["district"]
    }
    for feat in geojsons["province"]:
        adcode = str(feat["properties"]["adcode"])
        prefix2 = adcode[:2]
        name = feat["properties"]["name"]
        # Taiwan (71) may have no districts in DataV
        if prefix2 == "71":
            continue
        if prefix2 not in district_prov_prefixes:
            errors.append(ValidationError(
                "COVERAGE", f"Province {name} ({adcode}) has zero districts"
            ))

    # ── 8. Admin tree consistency ─────────────────────────────────────
    admin_path = DATA_DIR_ / "china_admin.json"
    admin = json.loads(admin_path.read_text(encoding="utf-8"))

    admin_prov_codes = {code for code, _ in admin["provinces"]}
    geojson_prov_codes = {str(f["properties"]["adcode"]) for f in geojsons["province"]}
    missing_in_admin = geojson_prov_codes - admin_prov_codes
    missing_in_geojson = admin_prov_codes - geojson_prov_codes
    if missing_in_admin:
        errors.append(ValidationError(
            "TREE_SYNC",
            f"Provinces in GeoJSON but not in admin tree: {sorted(missing_in_admin)}",
        ))
    if missing_in_geojson:
        errors.append(ValidationError(
            "TREE_SYNC",
            f"Provinces in admin tree but not in GeoJSON: {sorted(missing_in_geojson)}",
        ))

    admin_city_codes = {code for code, _ in admin["cities"]}
    if admin_city_codes != city_codes:
        errors.append(ValidationError(
            "TREE_SYNC",
            f"City codes differ between admin tree and GeoJSON: "
            f"only in tree {sorted(admin_city_codes - city_codes)[:10]}, "
            f"only in GeoJSON {sorted(city_codes - admin_city_codes)[:10]}",
        ))

    admin_dist_codes = {code for code, _ in admin["districts"]}
    geojson_dist_codes = {str(f["properties"]["adcode"]) for f in geojsons["district"]}
    dist_only_admin = admin_dist_codes - geojson_dist_codes
    dist_only_geojson = geojson_dist_codes - admin_dist_codes
    if dist_only_admin:
        errors.append(ValidationError(
            "TREE_SYNC",
            f"{len(dist_only_admin)} districts in admin tree but not in GeoJSON: "
            f"{sorted(list(dist_only_admin)[:10])}{'...' if len(dist_only_admin) > 10 else ''}",
            severity="WARN",
        ))
    if dist_only_geojson:
        errors.append(ValidationError(
            "TREE_SYNC",
            f"{len(dist_only_geojson)} districts in GeoJSON but not in admin tree: "
            f"{sorted(list(dist_only_geojson)[:10])}{'...' if len(dist_only_geojson) > 10 else ''}",
            severity="WARN",
        ))

    # ── 9. Landmark spot checks, against the data being validated ─────
    # Not through GeoTool: in version 3 that loads the previously built
    # .gtc, so it would validate last month's data and pass on anything.
    try:
        from shapely.geometry import Point, shape  # noqa: PLC0415
        from shapely import make_valid  # noqa: PLC0415
    except ImportError:
        errors.append(ValidationError(
            "LANDMARK", "Skipped landmark checks (shapely not installed)", severity="WARN",
        ))
    else:
        provinces = [
            (str(f["properties"]["adcode"]), f["properties"]["name"],
             make_valid(shape(f["geometry"])))
            for f in geojsons["province"] if f.get("geometry")
        ]
        for lat, lng, expected_prefix, label in LANDMARKS:
            point = Point(lng, lat)
            hits = [(code, name) for code, name, geom in provinces if geom.contains(point)]
            if not hits:
                errors.append(ValidationError(
                    "LANDMARK",
                    f"{label} ({lat}, {lng}) falls in no province polygon — "
                    f"coordinates not WGS-84, or converted twice?",
                ))
            elif not any(code.startswith(expected_prefix) for code, _ in hits):
                errors.append(ValidationError(
                    "LANDMARK",
                    f"{label} ({lat}, {lng}) expected province prefix "
                    f"{expected_prefix!r}, got {hits}",
                ))

    # ── 10. DATA_VERSION.json sanity ──────────────────────────────────
    version_path = DATA_DIR_ / "DATA_VERSION.json"
    version = json.loads(version_path.read_text(encoding="utf-8"))
    for key in ("source", "fetched_at", "counts"):
        if key not in version:
            errors.append(ValidationError(
                "VERSION", f"DATA_VERSION.json missing required key: {key!r}"
            ))
    if "counts" in version:
        for level_key in ("provinces", "cities", "districts"):
            vc = version["counts"].get(level_key, 0)
            actual = len(geojsons.get(
                {"provinces": "province", "cities": "city", "districts": "district"}[level_key],
                [],
            ))
            if vc != actual:
                errors.append(ValidationError(
                    "VERSION",
                    f"DATA_VERSION.json counts.{level_key}={vc} but "
                    f"actual GeoJSON has {actual} features",
                ))

    return errors


def main():
    print("Validating GeoToolCN data...\n")
    errors = validate()

    warns = [e for e in errors if e.severity == "WARN"]
    errs = [e for e in errors if e.severity == "ERROR"]

    if warns:
        print(f"Warnings ({len(warns)}):")
        for w in warns:
            print(f"  {w}")
        print()

    if errs:
        print(f"ERRORS ({len(errs)}):")
        for e in errs:
            print(f"  {e}")
        print(f"\nValidation FAILED with {len(errs)} error(s).")
        sys.exit(1)
    else:
        print(f"Validation PASSED ({len(warns)} warning(s)).")


if __name__ == "__main__":
    main()
