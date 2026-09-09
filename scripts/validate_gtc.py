"""L0 pipeline self-checks for a built .gtc (RFC-002 §L0).

    python scripts/validate_gtc.py                       # the shipped dataset
    python scripts/validate_gtc.py path/to/china.lite.gtc

Run after pipeline/build_gtc.py. These check the *artifact*, not the behaviour:
conformance already covers behaviour, but only against a file that loads at all.
A truncated section or a district with no resolvable parent would surface there
as a wall of unrelated failures.

Geometry checks need shapely; they are skipped with a warning when it is absent,
so this still runs in an environment that only consumes the package.
"""
from __future__ import annotations

import json
import math
import random
import struct
import subprocess
import sys
import zlib
from pathlib import Path

_PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(_PROJECT_ROOT))

from GeoToolCN._gtc import LEVELS, GTCData  # noqa: E402
from GeoToolCN._hierarchy import parent_city_code  # noqa: E402

DATA_DIR = _PROJECT_ROOT / "GeoToolCN" / "data"
DEFAULT_GTC = DATA_DIR / "china.full.gtc"

# A representative point recomputed from quantised geometry drifts; the pipeline
# stores the original-precision value instead. This bounds how far the stored
# point may sit from the polygon it names.
MAX_REPRESENTATIVE_DRIFT_M = 5.0

GRID_SAMPLE = 20_000
# Mixed cells are sampled; solid runs are not. Sampling 2,000 of 30,400 runs
# left a tampered run undetected 93% of the time — and one wrong run silently
# mis-attributes every point in a whole block of cells.
MIXED_SAMPLE = 2_000

_METRES_PER_DEGREE = 111_320.0


class Problem:
    def __init__(self, category: str, message: str, severity: str = "ERROR") -> None:
        self.category = category
        self.message = message
        self.severity = severity

    def __str__(self) -> str:
        return f"[{self.severity}] {self.category}: {self.message}"


def check_header(data: GTCData, problems: list[Problem]) -> None:
    if data.precision not in (4, 5):
        problems.append(Problem("HEADER", f"unexpected precision 1e-{data.precision}"))
    if data.dataset != 0:
        if not (0 < data.grid_step <= 0.5):
            problems.append(Problem("HEADER", f"implausible grid step {data.grid_step}"))
        if data.grid_width == 0 or data.grid_height == 0:
            problems.append(Problem("HEADER", "grid dimensions are zero"))
    version_path = DATA_DIR / "DATA_VERSION.json"
    if version_path.exists():
        stamp = int(json.loads(version_path.read_text(encoding="utf-8"))["fetched_at"].replace("-", ""))
        if data.data_version != stamp:
            problems.append(Problem(
                "HEADER",
                f"data_version {data.data_version} does not match "
                f"DATA_VERSION.json ({stamp}) — the .gtc is stale",
            ))


def check_checksums(path: Path, problems: list[Problem]) -> None:
    raw = path.read_bytes()
    section_count = struct.unpack_from("<H", raw, 12)[0]
    for i in range(section_count):
        base = 32 + 24 * i
        section_type, _, crc, offset, length = struct.unpack_from("<HHIQQ", raw, base)
        actual = zlib.crc32(raw[offset : offset + length])
        if actual != crc:
            problems.append(Problem(
                "CRC", f"section {section_type} checksum {actual:#x} != {crc:#x}"
            ))


def check_metadata(data: GTCData, problems: list[Problem]) -> None:
    seen: dict[str, set[str]] = {level: set() for level in LEVELS}
    for i in range(data.record_count):
        code = data.adcodes[i]
        level = LEVELS[data.levels[i]]
        if len(code) != 6 or not code.isdigit():
            problems.append(Problem("META", f"malformed adcode {code!r}"))
        if code in seen[level]:
            problems.append(Problem("META", f"duplicate adcode {code} at level {level}"))
        seen[level].add(code)
        if not data.names[i]:
            problems.append(Problem("META", f"{code} has an empty name"))

    # Records must be sorted by (level, adcode): the reader derives each level's
    # range by assuming contiguity, and the grid stores record indexes.
    keys = [(data.levels[i], data.adcodes[i]) for i in range(data.record_count)]
    if keys != sorted(keys):
        problems.append(Problem("META", "records are not sorted by (level, adcode)"))


def check_parents(data: GTCData, problems: list[Problem]) -> None:
    """Every district must resolve a parent city — 2874 of 2874, not 2873.

    The naive adcode[:4]+"00" rule silently yields nothing for the 30
    province-directly-governed county-level divisions, and a missing parent
    surfaces later as a null city rather than as an error.
    """
    city_codes = {
        data.adcodes[i]
        for i in range(*data.level_ranges["city"])
    }
    start, end = data.level_ranges["district"]
    missing = []
    wrong = []
    for i in range(start, end):
        code = data.adcodes[i]
        stored = data.parents[i]
        expected = parent_city_code(code, city_codes)
        if stored is None:
            missing.append(code)
        elif stored != expected:
            wrong.append(f"{code}: stored {stored}, rules say {expected}")
    if missing:
        problems.append(Problem(
            "PARENT",
            f"{len(missing)}/{end - start} districts have no parent city: {missing[:10]}",
        ))
    if wrong:
        problems.append(Problem(
            "PARENT", f"{len(wrong)} parents disagree with the rules: {wrong[:5]}"
        ))

    for i in range(*data.level_ranges["city"]):
        expected = data.adcodes[i][:2] + "0000"
        if data.parents[i] != expected:
            problems.append(Problem(
                "PARENT", f"city {data.adcodes[i]} parent is {data.parents[i]}, expected {expected}"
            ))


def check_representative_points(data: GTCData, problems: list[Problem]) -> None:
    """The stored point must lie inside the region it names."""
    if not data.has_geometry:
        return
    offenders = []
    for level in ("province", "district"):
        for i in range(*data.level_ranges[level]):
            if data.geometry(i) is None:
                continue
            qx = data.lngs[i] * data.scale
            qy = data.lats[i] * data.scale
            if not data.contains(i, qx, qy):
                offenders.append(f"{data.names[i]}({data.adcodes[i]})")
    if offenders:
        problems.append(Problem(
            "REPPOINT",
            f"{len(offenders)} regions do not contain their own representative "
            f"point: {offenders[:10]}",
        ))


def check_grid(data: GTCData, problems: list[Problem]) -> None:
    """Solid cells claim a region covers them wholly; spot-check that claim.

    A wrong run boundary is invisible to conformance unless a sampled point
    happens to land in the mis-attributed cells.
    """
    if not data.has_geometry:
        return
    rng = random.Random(7)

    for label, grid in (("district", data._district_grid), ("province", data._province_grid)):
        run_start, run_length, run_value, mixed_cells, mixed_ptrs, mixed_lists = grid

        # Runs must be sorted, non-overlapping and confined to a single row.
        previous_end = -1
        for i in range(len(run_start)):
            start = run_start[i]
            end = start + run_length[i] - 1
            if start <= previous_end:
                problems.append(Problem("GRID", f"{label} runs overlap at index {i}"))
                break
            if start // data.grid_width != end // data.grid_width:
                problems.append(Problem("GRID", f"{label} run at {start} spans a row boundary"))
                break
            previous_end = end

        if list(mixed_cells) != sorted(mixed_cells):
            problems.append(Problem("GRID", f"{label} mixed cells are not sorted"))
        if len(mixed_ptrs) != len(mixed_cells) + 1:
            problems.append(Problem("GRID", f"{label} mixed pointer table has the wrong length"))
        elif mixed_ptrs[-1] != len(mixed_lists):
            problems.append(Problem("GRID", f"{label} mixed pointers do not span the candidate list"))

        # Candidates within a cell must ascend by adcode: the tie-break rule
        # depends on it (SPEC §3.4).
        for k in rng.sample(range(len(mixed_cells)), min(MIXED_SAMPLE, len(mixed_cells))):
            candidates = mixed_lists[mixed_ptrs[k] : mixed_ptrs[k + 1]]
            codes = [data.adcodes[c] for c in candidates]
            if codes != sorted(codes):
                problems.append(Problem(
                    "GRID", f"{label} cell {mixed_cells[k]} candidates are not adcode-ordered"
                ))
                break

        # Every solid run: the named region must contain the centre of a cell
        # in it. Exhaustive because a single wrong run value mis-attributes an
        # entire block of cells, and there are only ~36k runs across both grids.
        bad = []
        for i in range(len(run_start)):
            cell = int(run_start[i]) + rng.randrange(int(run_length[i]))
            row, col = divmod(cell, data.grid_width)
            lng = data.origin_lng + (col + 0.5) * data.grid_step
            lat = data.origin_lat + (row + 0.5) * data.grid_step
            if not data.contains(int(run_value[i]), lng * data.scale, lat * data.scale):
                bad.append(f"run {i}@{run_start[i]} -> {data.adcodes[int(run_value[i])]}")
        if bad:
            problems.append(Problem(
                "GRID",
                f"{label}: {len(bad)}/{len(run_start)} solid runs name a region that "
                f"does not cover them: {bad[:5]}",
            ))


def check_grid_agrees_with_geometry(data: GTCData, problems: list[Problem]) -> None:
    """Cross-check the index against the geometry it was derived from.

    Needs shapely, so it is skipped where the package is merely consumed.
    """
    if not data.has_geometry:
        return
    try:
        from shapely.geometry import Point  # noqa: PLC0415
        from shapely import STRtree, make_valid  # noqa: PLC0415
        from shapely.geometry import shape  # noqa: PLC0415
    except ImportError:
        problems.append(Problem(
            "GRID", "shapely absent — skipped the index/geometry cross-check", "WARN"
        ))
        return

    source = DATA_DIR / "china_district.geojson"
    if not source.exists():
        problems.append(Problem("GRID", "source GeoJSON absent — skipped cross-check", "WARN"))
        return

    raw = json.loads(source.read_text(encoding="utf-8"))
    geometries = []
    codes = []
    for feature in raw["features"]:
        if feature["geometry"]:
            geometries.append(make_valid(shape(feature["geometry"])))
            codes.append(str(feature["properties"]["adcode"]))
    tree = STRtree(geometries)

    rng = random.Random(11)
    mismatched = []
    for _ in range(GRID_SAMPLE):
        lat = rng.uniform(3.5, 53.5)
        lng = rng.uniform(73.5, 135.5)
        index = data.locate(lat, lng)
        from_gtc = data.adcodes[index] if index is not None else None

        point = Point(lng, lat)
        hits = sorted(
            (codes[i] for i in tree.query(point, predicate="intersects")
             if geometries[i].contains(point))
        )
        from_source = hits[0] if hits else None

        if from_gtc != from_source:
            mismatched.append((round(lat, 6), round(lng, 6), from_source, from_gtc))

    # Quantisation legitimately flips attribution within ~1 m of a boundary
    # (DIV-104), so a handful is expected; a systematic break is not.
    rate = len(mismatched) / GRID_SAMPLE
    if rate > 0.005:
        problems.append(Problem(
            "GRID",
            f"index disagrees with source geometry on {len(mismatched)}/{GRID_SAMPLE} "
            f"points ({rate:.2%}, threshold 0.5%): {mismatched[:5]}",
        ))
    elif mismatched:
        problems.append(Problem(
            "GRID",
            f"{len(mismatched)}/{GRID_SAMPLE} boundary points differ from source "
            f"geometry ({rate:.3%}) — expected from quantisation",
            "WARN",
        ))


def check_round_trip(path: Path, problems: list[Problem]) -> None:
    """Rebuilding from the same input must reproduce the file byte for byte.

    A build that is not deterministic makes the CI freshness check unusable and
    turns every data refresh into an unreviewable diff.
    """
    dataset = {0: "mini", 1: "lite", 2: "full"}[path.read_bytes()[6]]
    rebuilt = Path("/tmp") / f"roundtrip.{dataset}.gtc"
    result = subprocess.run(
        [sys.executable, str(_PROJECT_ROOT / "pipeline" / "build_gtc.py"),
         "--dataset", dataset, "--out", str(rebuilt)],
        capture_output=True,
        text=True,
    )
    if result.returncode != 0:
        problems.append(Problem(
            "ROUNDTRIP", f"rebuild failed: {result.stderr.strip()[:300]}", "WARN"
        ))
        return
    if rebuilt.read_bytes() != path.read_bytes():
        problems.append(Problem(
            "ROUNDTRIP", f"rebuilding {path.name} produced different bytes — build is not deterministic"
        ))
    rebuilt.unlink(missing_ok=True)


def validate(path: Path, *, round_trip: bool) -> list[Problem]:
    problems: list[Problem] = []
    if not path.exists():
        return [Problem("FILE", f"{path} does not exist — run pipeline/build_gtc.py")]

    # Checksums first: a corrupt section makes every later check report noise
    # instead of the actual problem.
    check_checksums(path, problems)
    if any(p.category == "CRC" for p in problems):
        return problems

    try:
        data = GTCData(str(path), verify_checksums=False)
    except Exception as exc:  # noqa: BLE001 - reported, not raised
        problems.append(Problem("LOAD", f"could not load: {type(exc).__name__}: {exc}"))
        return problems

    check_header(data, problems)
    check_metadata(data, problems)
    check_parents(data, problems)
    check_representative_points(data, problems)
    check_grid(data, problems)
    check_grid_agrees_with_geometry(data, problems)
    if round_trip:
        check_round_trip(path, problems)
    return problems


def main() -> int:
    args = [a for a in sys.argv[1:] if not a.startswith("-")]
    round_trip = "--round-trip" in sys.argv
    path = Path(args[0]) if args else DEFAULT_GTC

    print(f"Validating {path.name}...\n")
    problems = validate(path, round_trip=round_trip)

    warnings = [p for p in problems if p.severity == "WARN"]
    errors = [p for p in problems if p.severity == "ERROR"]

    for warning in warnings:
        print(f"  {warning}")
    if warnings:
        print()

    if errors:
        print(f"ERRORS ({len(errors)}):")
        for error in errors:
            print(f"  {error}")
        print(f"\nValidation FAILED with {len(errors)} error(s).")
        return 1

    print(f"Validation PASSED ({len(warnings)} warning(s)).")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
