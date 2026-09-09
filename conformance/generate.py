"""Generate the language-neutral conformance suite from the reference implementation.

The suite is what every GeoToolCN port — in any language — is checked against.
It is regenerated when the bundled DataV data changes; review the resulting diff
before committing (see docs/RFC-002-testing-and-acceptance.md §6).

    python conformance/generate.py

Sampling is stratified rather than uniform.  Uniform random points overwhelmingly
land in large rural districts, which is precisely where nothing interesting
happens: every defect found while designing this suite sat on a boundary, an
island, or an administratively irregular division.  The strata below deliberately
over-sample those.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import math
import os
import random
import shutil
import sys
import tempfile
from pathlib import Path

_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(_ROOT))

from GeoToolCN import (  # noqa: E402
    GeoTool,
    bd09_to_gcj02,
    bd09_to_wgs84,
    distance,
    gcj02_to_bd09,
    gcj02_to_wgs84,
    get_administrative_tree,
    wgs84_to_bd09,
    wgs84_to_gcj02,
)

OUT_DIR = Path(__file__).resolve().parent
SEED = 20260909

# Coordinate conversions go through sin/cos, and libm differs between platforms
# in the last couple of digits. Stored at 12 decimals those differences show up,
# so coords.jsonl cannot be compared byte for byte across machines — the freshness
# check compares it numerically, at the same tolerance the suite itself applies.
FRESHNESS_TOLERANCE = {"coords.jsonl": 1e-9}

BOUNDARY_PER_DISTRICT = 3
UNIFORM_SAMPLES = 5000
OUTSIDE_SAMPLES = 500

MERGED_PREFIXES = frozenset({"11", "12", "31", "50", "81", "82"})

# Divisions that exposed defects during design; pinned so a future refactor
# cannot silently lose them.  See conformance/known-divergences.yaml.
PINNED_POINTS = [
    (30.66457, 122.56396, "island"),        # 嵊泗县
    (28.04746, 121.13337, "island"),        # 玉环市
    (30.21028, 105.65155, "island"),        # 重庆潼南区
    (45.02629, 82.58717, "island"),         # 新疆博乐市
    (40.87535, 109.89243, "layer-conflict"),  # 乌拉特前旗
    (30.97038, 120.72639, "layer-conflict"),  # 秀洲区
    (27.88370, 119.79201, "layer-conflict"),  # 景宁县
    (33.02129, 116.04690, "layer-conflict"),  # 利辛县
    (23.06839, 115.93772, "layer-conflict"),  # 惠来县
    (50.37295, 124.16537, "enclave"),       # 加格达奇区
    (22.97637, 110.74743, "district-gap"),  # DIV-101 的样本
]

OUTSIDE_POINTS = [
    (35.6762, 139.6503, "abroad"),    # 东京
    (37.5665, 126.9780, "abroad"),    # 首尔
    (0.0, 0.0, "null-island"),
    (-33.8688, 151.2093, "abroad"),   # 悉尼
    (55.0, 100.0, "abroad"),          # 蒙古/俄罗斯境内
    (20.0, 115.0, "ocean"),           # 南海
    (30.0, 125.0, "ocean"),           # 东海
    (90.0, 180.0, "extreme"),
    (-90.0, -180.0, "extreme"),
]


def region_codes(result) -> list[str | None]:
    return [
        result.province.code if result.province else None,
        result.city.code if result.city else None,
        result.district.code if result.district else None,
    ]


def write_jsonl(name: str, rows: list[dict]) -> int:
    path = OUT_DIR / name
    with open(path, "w", encoding="utf-8") as f:
        for row in rows:
            f.write(json.dumps(row, ensure_ascii=False, separators=(",", ":")) + "\n")
    size = path.stat().st_size
    print(f"  {name:22s} {len(rows):>7,} 条  {size / 1024:>8.1f} KB")
    return len(rows)


def boundary_points(geometry, count: int, rng: random.Random):
    """Sample points near the outline, where the layers actually disagree."""
    try:
        rings = []
        if geometry.geom_type == "Polygon":
            rings = [geometry.exterior]
        elif geometry.geom_type == "MultiPolygon":
            rings = [p.exterior for p in geometry.geoms]
        if not rings:
            return []
        out = []
        for _ in range(count):
            ring = rings[rng.randrange(len(rings))]
            if ring.length == 0:
                continue
            pt = ring.interpolate(rng.random(), normalized=True)
            # Nudge off the line so the point is unambiguously in or out.
            jitter = 0.002
            out.append(
                (
                    round(pt.y + rng.uniform(-jitter, jitter), 6),
                    round(pt.x + rng.uniform(-jitter, jitter), 6),
                )
            )
        return out
    except Exception:
        return []


def compare_against_committed(generated_dir: Path) -> list[str]:
    """Report how a freshly generated suite differs from the committed one."""
    problems: list[str] = []
    for path in sorted(generated_dir.iterdir()):
        committed = OUT_DIR / path.name
        if not committed.exists():
            problems.append(f"{path.name}: missing from the repository")
            continue
        tolerance = FRESHNESS_TOLERANCE.get(path.name)
        if tolerance is None:
            if committed.read_bytes() != path.read_bytes():
                problems.append(f"{path.name}: differs")
            continue

        want = [json.loads(line) for line in committed.read_text("utf-8").splitlines() if line]
        got = [json.loads(line) for line in path.read_text("utf-8").splitlines() if line]
        if len(want) != len(got):
            problems.append(f"{path.name}: {len(want)} cases committed, {len(got)} generated")
            continue
        drifted = 0
        for a, b in zip(want, got):
            if a["id"] != b["id"] or a["in"] != b["in"]:
                problems.append(f"{path.name}: case {a['id']} changed shape")
                break
            aw, bw = a["out"], b["out"]
            aw = aw if isinstance(aw, list) else [aw]
            bw = bw if isinstance(bw, list) else [bw]
            if any(abs(x - y) > tolerance for x, y in zip(aw, bw)):
                drifted += 1
        if drifted:
            problems.append(
                f"{path.name}: {drifted}/{len(want)} cases differ by more than {tolerance}"
            )
    return problems


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--check",
        action="store_true",
        help="regenerate into a temporary directory and report differences "
        "instead of overwriting the committed suite",
    )
    args = parser.parse_args()

    global OUT_DIR
    committed_dir = OUT_DIR
    temp_dir = None
    if args.check:
        temp_dir = Path(tempfile.mkdtemp(prefix="conformance-check-"))
        OUT_DIR = temp_dir

    print("Generating conformance suite from the reference implementation...\n")
    geo = GeoTool()
    rng = random.Random(SEED)

    provinces = geo.list_regions("province")
    cities = geo.list_regions("city")
    districts = geo.list_regions("district")
    city_codes = {c.code for c in cities}
    all_regions = provinces + cities + districts

    # ---------------- reverse.jsonl ----------------
    samples: list[tuple[float, float, list[str]]] = []

    for r in districts:
        tags = ["representative"]
        if r.code[:2] in MERGED_PREFIXES:
            tags.append("merged-prefix")
        if r.code[:4] in ("4190", "4290", "4690", "6590"):
            tags.append("province-governed")
        if r.code in city_codes:
            tags.append("city-and-district")
        samples.append((r.latitude, r.longitude, tags))

    # Boundary sampling needs real geometry, which the shipped implementation
    # does not expose; borrow it from the reference. Expected values still come
    # from the shipped implementation — it is the one the spec describes.
    from reference.geopandas_impl import GeoTool as ReferenceGeoTool  # noqa: PLC0415

    gdf = ReferenceGeoTool()._levels["district"].gdf
    for i in range(len(gdf)):
        for lat, lng in boundary_points(gdf.iloc[i].geometry, BOUNDARY_PER_DISTRICT, rng):
            samples.append((lat, lng, ["boundary"]))

    for lat, lng, tag in PINNED_POINTS:
        samples.append((lat, lng, ["pinned", tag]))

    for lat, lng, tag in OUTSIDE_POINTS:
        samples.append((lat, lng, ["outside", tag]))

    for _ in range(UNIFORM_SAMPLES):
        samples.append(
            (round(rng.uniform(3.0, 54.0), 6), round(rng.uniform(73.0, 136.0), 6),
             ["uniform"])
        )
    for _ in range(OUTSIDE_SAMPLES):
        samples.append(
            (round(rng.uniform(-60.0, 80.0), 6), round(rng.uniform(-180.0, 180.0), 6),
             ["global"])
        )

    rows = []
    for i, (lat, lng, tags) in enumerate(samples):
        rows.append(
            {
                "id": f"rev-{i:06d}",
                "tags": tags,
                "in": [lat, lng],
                "out": region_codes(geo.reverse(lat, lng)),
            }
        )
    n_reverse = write_jsonl("reverse.jsonl", rows)

    # ---------------- lookup.jsonl ----------------
    rows = []
    for i, r in enumerate(all_regions):
        result = geo.lookup_adcode(r.code)
        rows.append(
            {
                "id": f"lkp-{i:06d}",
                "tags": [r.level],
                "in": r.code,
                "out": region_codes(result) if result else None,
            }
        )
    for i, bad in enumerate(["", "abc", "12345", "1234567", "999999", "110", "00000a"]):
        rows.append(
            {"id": f"lkp-bad-{i:03d}", "tags": ["invalid"], "in": bad, "out": None}
        )
    n_lookup = write_jsonl("lookup.jsonl", rows)

    # ---------------- search.jsonl ----------------
    rows = []
    idx = 0

    def add_search(query, tags, **kwargs):
        nonlocal idx
        params = {k: v for k, v in kwargs.items() if v is not None}
        results = geo.search(query, **kwargs)
        rows.append(
            {
                "id": f"sch-{idx:06d}",
                "tags": tags,
                "in": {"query": query, **params},
                "out": [r.code for r in results],
            }
        )
        idx += 1

    for r in all_regions:
        add_search(r.name, ["exact", r.level], level=r.level)

    # Ambiguous names, parent disambiguation, and the island case that the old
    # geometry-based filter dropped.
    # Substrings taken from the middle of names. Without these the fuzzy path is
    # barely exercised: nearly every case above matches exactly, so swapping
    # `contains` for `startswith` changed exactly one expected result.
    fuzzy_seen: set[str] = set()
    for r in rng.sample(districts, 250):
        if len(r.name) >= 3:
            fragment = r.name[1:3]
            if fragment not in fuzzy_seen:
                fuzzy_seen.add(fragment)
                add_search(fragment, ["fuzzy", "infix"], level="district")
    for fragment in ["阳区", "自治县", "尔族", "新区", "开发区", "林区", "群岛", "特别"]:
        if fragment not in fuzzy_seen:
            fuzzy_seen.add(fragment)
            add_search(fragment, ["fuzzy", "infix", "pinned"])

    for query, kwargs, tags in [
        ("朝阳区", {"level": "district"}, ["ambiguous"]),
        ("朝阳区", {"province": "北京市"}, ["parent-filter", "by-name"]),
        ("朝阳区", {"province": "110000"}, ["parent-filter", "by-code"]),
        ("朝阳区", {"city": "长春市"}, ["parent-filter", "city"]),
        ("朝阳区", {"province": "广东省"}, ["parent-filter", "no-match"]),
        ("嵊泗县", {"province": "浙江省"}, ["parent-filter", "island"]),
        ("玉环市", {"province": "浙江省"}, ["parent-filter", "island"]),
        ("济源市", {"province": "河南省"}, ["province-governed"]),
        ("东莞市", {}, ["city-and-district"]),
        ("深圳", {}, ["fuzzy"]),
        ("深圳", {"fuzzy": False}, ["fuzzy-off"]),
        ("110000", {}, ["by-code"]),
        ("440300", {}, ["by-code"]),
        ("不存在的地方xyz", {}, ["no-match"]),
        # Regex metacharacters: literal under the spec, so all of these miss.
        ("东.区", {"level": "district"}, ["metachar"]),
        ("西城|东城", {"level": "district"}, ["metachar"]),
        ("北京(市)", {}, ["metachar"]),
        ("[", {}, ["metachar"]),
        ("*", {}, ["metachar"]),
        ("市", {"level": "province"}, ["fuzzy", "common-substring"]),
    ]:
        add_search(query, tags, **kwargs)
    n_search = write_jsonl("search.jsonl", rows)

    # ---------------- coords.jsonl ----------------
    conversions = [
        ("wgs84_to_gcj02", wgs84_to_gcj02),
        ("gcj02_to_wgs84", gcj02_to_wgs84),
        ("gcj02_to_bd09", gcj02_to_bd09),
        ("bd09_to_gcj02", bd09_to_gcj02),
        ("wgs84_to_bd09", wgs84_to_bd09),
        ("bd09_to_wgs84", bd09_to_wgs84),
    ]
    coord_points = [(r.latitude, r.longitude) for r in provinces + cities]
    coord_points += [(lat, lng) for lat, lng, _ in OUTSIDE_POINTS]
    coord_points += [
        (round(rng.uniform(3.0, 54.0), 6), round(rng.uniform(73.0, 136.0), 6))
        for _ in range(1000)
    ]
    # The out-of-China bbox gates whether the GCJ-02 offset is applied at all.
    # Points must straddle each bound: sitting exactly on it leaves the branch
    # unexercised, since `<` is false on both sides of a moved threshold.
    for lat_in, lng_in in [(30.0, 137.5), (30.0, 72.5), (1.0, 100.0), (55.5, 100.0)]:
        coord_points.append((lat_in, lng_in))          # just inside
    for lat_out, lng_out in [(30.0, 138.5), (30.0, 71.5), (0.5, 100.0), (56.5, 100.0)]:
        coord_points.append((lat_out, lng_out))        # just outside
    coord_points += [
        (0.8293, 72.004), (55.8271, 137.8347),         # exactly on the corners
        (0.8294, 72.005), (55.8270, 137.8346),
    ]
    # NOTE: the conversion functions take (lng, lat) — longitude first — while
    # distance() and every GeoTool method take latitude first.  Passing them the
    # wrong way round does not raise: the swapped values fall outside the China
    # bounding box, so the input is returned unchanged and the bug is silent.
    # "in" therefore records the literal argument list, which the runner replays.
    rows = []
    for i, (lat, lng) in enumerate(coord_points):
        for name, fn in conversions:
            got = fn(lng, lat)
            rows.append(
                {
                    "id": f"crd-{i:06d}-{name}",
                    "tags": [name],
                    "fn": name,
                    "in": [lng, lat],
                    "out": [round(got[0], 12), round(got[1], 12)],
                }
            )
    for i, (a, b) in enumerate(
        [
            ((39.9042, 116.4074), (31.2304, 121.4737)),   # 京 → 沪
            ((0.0, 0.0), (0.0, 0.0)),                     # 零距离
            ((22.5431, 114.0579), (22.5431, 114.0579)),   # 同点
            ((-33.8688, 151.2093), (35.6762, 139.6503)),  # 跨半球
            ((0.0, 0.0), (0.0, 180.0)),                   # 半周长
            ((90.0, 0.0), (-90.0, 0.0)),                  # 极点对跖
            ((39.9042, 116.4074), (39.9142, 116.4074)),   # 约 1 km，纬向
            ((39.9042, 116.4074), (39.9042, 116.4174)),   # 约 1 km，经向
        ]
    ):
        rows.append(
            {
                "id": f"crd-dist-{i:03d}",
                "tags": ["distance"],
                "fn": "distance",
                "in": [a[0], a[1], b[0], b[1]],
                "out": round(distance(a[0], a[1], b[0], b[1]), 12),
            }
        )
    n_coords = write_jsonl("coords.jsonl", rows)

    # ---------------- containment.jsonl ----------------
    rows = []
    idx = 0
    for r in all_regions:
        rows.append(
            {
                "id": f"cnt-{idx:06d}",
                "tags": ["is_in_region", "self", r.level],
                "fn": "is_in_region",
                "in": [r.latitude, r.longitude, r.code],
                "out": geo.is_in_region(r.latitude, r.longitude, r.code),
            }
        )
        idx += 1
    for lat, lng, tag in PINNED_POINTS + OUTSIDE_POINTS:
        rows.append(
            {
                "id": f"cnt-{idx:06d}",
                "tags": ["is_in_china", tag],
                "fn": "is_in_china",
                "in": [lat, lng],
                "out": geo.is_in_china(lat, lng),
            }
        )
        idx += 1
    # Cross pairs: a Beijing point is not in Shenzhen, and vice versa.
    for lat, lng, code in [
        (39.9042, 116.4074, "440300"),
        (22.5431, 114.0579, "110000"),
        (39.9042, 116.4074, "110000"),
        (22.5431, 114.0579, "440300"),
    ]:
        rows.append(
            {
                "id": f"cnt-{idx:06d}",
                "tags": ["is_in_region", "cross"],
                "fn": "is_in_region",
                "in": [lat, lng, code],
                "out": geo.is_in_region(lat, lng, code),
            }
        )
        idx += 1
    for bad in ["xyz", "999999", "", "1234567"]:
        rows.append(
            {
                "id": f"cnt-{idx:06d}",
                "tags": ["is_in_region", "invalid"],
                "fn": "is_in_region",
                "in": [39.9042, 116.4074, bad],
                "out": "error",
            }
        )
        idx += 1
    n_containment = write_jsonl("containment.jsonl", rows)

    # ---------------- tree.json ----------------
    tree = get_administrative_tree()
    canonical = json.dumps(tree, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    digest = hashlib.sha256(canonical.encode("utf-8")).hexdigest()
    (OUT_DIR / "tree.sha256").write_text(digest + "\n", encoding="utf-8")
    leaves = sum(
        len(city.get("children", [])) for prov in tree for city in prov["children"]
    )
    print(f"  {'tree.sha256':22s} {len(tree)} 省 / {leaves:,} 区县  {digest[:16]}...")

    # ---------------- manifest ----------------
    data_version = json.loads(
        (_ROOT / "GeoToolCN" / "data" / "DATA_VERSION.json").read_text(encoding="utf-8")
    )
    manifest = {
        "spec_version": 1,
        "generated_from": "GeoToolCN (.gtc implementation)",
        "seed": SEED,
        "data_version": data_version,
        "counts": {
            "reverse": n_reverse,
            "lookup": n_lookup,
            "search": n_search,
            "coords": n_coords,
            "containment": n_containment,
        },
        "tree_sha256": digest,
    }
    (OUT_DIR / "manifest.json").write_text(
        json.dumps(manifest, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )
    total = n_reverse + n_lookup + n_search + n_coords + n_containment
    print(f"\n共 {total:,} 条用例。")

    if temp_dir is not None:
        OUT_DIR = committed_dir
        problems = compare_against_committed(temp_dir)
        shutil.rmtree(temp_dir, ignore_errors=True)
        if problems:
            print("\n数据集与当前实现不一致：")
            for problem in problems:
                print(f"  {problem}")
            print("\n请运行 python conformance/generate.py，审阅 diff 后提交。")
            raise SystemExit(1)
        print("数据集与当前实现一致。")


if __name__ == "__main__":
    main()
