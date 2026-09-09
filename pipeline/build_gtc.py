"""Build the .gtc binary from the bundled GeoJSON.

    python pipeline/build_gtc.py                 # full dataset
    python pipeline/build_gtc.py --dataset lite

Runs at build time only; the resulting file is what every language runtime
reads.  The format is specified in SPEC.md §4 — this script and any reader must
be changed together, with format_version bumped.

Everything expensive happens here so that runtimes stay trivial: the grid index
turns ~77% of lookups into a table read with no geometry at all, and the
remaining cells carry an average of 2 candidates.  That is what makes a ~600
line port viable in languages with no geometry library.
"""
from __future__ import annotations

import argparse
import json
import math
import struct
import sys
import time
import zlib
from collections import defaultdict
from pathlib import Path

import numpy as np
from shapely import STRtree, make_valid
from shapely.geometry import box, shape

_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(_ROOT))

from GeoToolCN._hierarchy import MERGED_PREFIXES, parent_city_code  # noqa: E402

DATA_DIR = _ROOT / "GeoToolCN" / "data"

MAGIC = b"GTCN"
FORMAT_VERSION = 1

# dataset id -> (name, quantisation exponent, grid step in degrees)
DATASETS = {
    "mini": (0, 5, None),
    "lite": (1, 4, 0.1),
    "full": (2, 5, 0.05),
}

LEVELS = ("province", "city", "district")
LEVEL_ID = {name: i for i, name in enumerate(LEVELS)}

# Grid coverage. Wide enough for the South China Sea and the Pamirs.
GRID_ORIGIN_LNG = 73.0
GRID_ORIGIN_LAT = 3.0
GRID_MAX_LNG = 136.0
GRID_MAX_LAT = 54.0

SECTION_META = 1
SECTION_NAMES = 2
SECTION_GEOM = 3
SECTION_GEOM_INDEX = 4
SECTION_GRID_SOLID = 5
SECTION_GRID_MIXED_CELLS = 6
SECTION_GRID_MIXED_PTRS = 7
SECTION_GRID_MIXED_LISTS = 8
# The province grid answers points that fall in no district: Taiwan carries
# province-level boundaries only, and coastal gaps leave slivers uncovered.
SECTION_GRID_PROV_SOLID = 9
SECTION_GRID_PROV_MIXED_CELLS = 10
SECTION_GRID_PROV_MIXED_PTRS = 11
SECTION_GRID_PROV_MIXED_LISTS = 12


def round_half_away(x: float) -> int:
    """SPEC §3.1.  Python's round() is banker's rounding and does not match."""
    return int(math.floor(abs(x) + 0.5)) * (1 if x >= 0 else -1)


def uvarint(n: int, out: bytearray) -> None:
    """Plain unsigned LEB128 — used for counts (SPEC §4.5)."""
    while True:
        byte = n & 0x7F
        n >>= 7
        out.append(byte | 0x80 if n else byte)
        if not n:
            return


def svarint(n: int, out: bytearray) -> None:
    """Zigzag + LEB128 — used for coordinates only (SPEC §4.5).

    Applying zigzag to counts as well is the mistake the prototype made: ring
    counts came back doubled and the decoder ran off the end of the section.
    """
    uvarint((n << 1) ^ (n >> 63), out)


def polygons_of(geometry):
    """Flatten to Polygons; make_valid can hand back a GeometryCollection."""
    kind = geometry.geom_type
    if kind == "Polygon":
        return [geometry]
    if kind == "MultiPolygon":
        return list(geometry.geoms)
    if kind == "GeometryCollection":
        out = []
        for sub in geometry.geoms:
            out += polygons_of(sub)
        return out
    return []


class Level:
    """One administrative level loaded from GeoJSON."""

    def __init__(self, name: str, path: Path) -> None:
        self.name = name
        raw = json.loads(path.read_text(encoding="utf-8"))
        self.codes: list[str] = []
        self.names: list[str] = []
        self.geometries: list = []
        self.reps: list[tuple[float, float]] = []
        for feature in raw["features"]:
            if not feature["geometry"]:
                continue
            geometry = make_valid(shape(feature["geometry"]))
            self.codes.append(str(feature["properties"]["adcode"]))
            self.names.append(feature["properties"]["name"])
            self.geometries.append(geometry)
            # SPEC §1.1: computed at ORIGINAL precision. Recomputing from the
            # quantised geometry at runtime shifts it by up to 1.6 m.
            point = geometry.representative_point()
            self.reps.append((round(point.y, 6), round(point.x, 6)))


def build_grid(level: Level, step: float, order: list[int]):
    """Classify every grid cell as empty, solid, or mixed (SPEC §4.6).

    ``order`` maps a level-local index to its record index in META, which is
    what the grid stores.
    """
    width = int(round((GRID_MAX_LNG - GRID_ORIGIN_LNG) / step))
    height = int(round((GRID_MAX_LAT - GRID_ORIGIN_LAT) / step))
    tree = STRtree(level.geometries)

    solid: list[tuple[int, int]] = []          # (cell_id, record_index)
    mixed: list[tuple[int, list[int]]] = []    # (cell_id, [record_index, ...])

    for col in range(width):
        x = GRID_ORIGIN_LNG + col * step
        cells = [
            box(x, GRID_ORIGIN_LAT + row * step, x + step, GRID_ORIGIN_LAT + (row + 1) * step)
            for row in range(height)
        ]
        hits = tree.query(np.array(cells, dtype=object), predicate="intersects")
        per_cell = defaultdict(list)
        for cell_idx, geom_idx in zip(hits[0], hits[1]):
            per_cell[int(cell_idx)].append(int(geom_idx))

        for cell_idx, candidates in per_cell.items():
            cell_id = cell_idx * width + col
            if len(candidates) == 1 and level.geometries[candidates[0]].covers(cells[cell_idx]):
                solid.append((cell_id, order[candidates[0]]))
            else:
                # SPEC §3.4: candidates are visited in ascending adcode order.
                mixed.append(
                    (cell_id, sorted(order[c] for c in candidates))
                )

    solid.sort()
    mixed.sort()

    # Run-length encode the solid cells. Runs must not straddle a row boundary,
    # so that a reader can recover (row, col) from any cell in the run.
    runs: list[tuple[int, int, int]] = []
    i = 0
    while i < len(solid):
        start, value = solid[i]
        length = 1
        while (
            i + length < len(solid)
            and solid[i + length][0] == start + length
            and solid[i + length][1] == value
            and (start + length) % width != 0
        ):
            length += 1
        runs.append((start, length, value))
        i += length

    return width, height, runs, mixed


def encode_geometry(geometry, scale: int) -> bytes:
    out = bytearray()
    minx, miny, maxx, maxy = geometry.bounds
    out += struct.pack(
        "<4i",
        round_half_away(minx * scale) - 1,
        round_half_away(miny * scale) - 1,
        round_half_away(maxx * scale) + 1,
        round_half_away(maxy * scale) + 1,
    )
    polygons = polygons_of(geometry)
    uvarint(len(polygons), out)
    for polygon in polygons:
        rings = [polygon.exterior, *polygon.interiors]
        uvarint(len(rings), out)
        for ring in rings:
            coords = list(ring.coords)
            uvarint(len(coords), out)
            prev_x = prev_y = 0
            for x, y in coords:
                qx = round_half_away(x * scale)
                qy = round_half_away(y * scale)
                svarint(qx - prev_x, out)
                svarint(qy - prev_y, out)
                prev_x, prev_y = qx, qy
    return bytes(out)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--dataset", choices=list(DATASETS), default="full")
    parser.add_argument("--out", type=Path, default=None)
    args = parser.parse_args()

    dataset_id, precision, grid_step = DATASETS[args.dataset]
    scale = 10 ** precision
    out_path = args.out or DATA_DIR / f"china.{args.dataset}.gtc"

    print(f"Building {args.dataset} dataset (precision 1e-{precision})\n")

    started = time.time()
    levels = {name: Level(name, DATA_DIR / f"china_{name}.geojson") for name in LEVELS}
    for name, level in levels.items():
        print(f"  loaded {name:9s} {len(level.codes):>5,}")

    # ---- META: sorted by (level, adcode); the row index is the record index --
    city_codes = set(levels["city"].codes)
    records = []
    for name in LEVELS:
        level = levels[name]
        for i, code in enumerate(level.codes):
            if name == "district":
                parent = parent_city_code(code, city_codes)
            elif name == "city":
                parent = code[:2] + "0000"
            else:
                parent = None
            records.append(
                {
                    "adcode": int(code),
                    "level": LEVEL_ID[name],
                    "parent": int(parent) if parent else 0,
                    "name": level.names[i],
                    "lat": level.reps[i][0],
                    "lng": level.reps[i][1],
                    "level_name": name,
                    "local_index": i,
                }
            )
    records.sort(key=lambda r: (r["level"], r["adcode"]))

    # level-local index -> record index, needed by the grid
    order = {name: [0] * len(levels[name].codes) for name in LEVELS}
    for record_index, record in enumerate(records):
        order[record["level_name"]][record["local_index"]] = record_index

    unresolved = [
        r["adcode"] for r in records if r["level_name"] == "district" and not r["parent"]
    ]
    if unresolved:
        raise SystemExit(
            f"{len(unresolved)} districts have no parent city: {unresolved[:10]}"
        )

    names_blob = bytearray()
    name_slices = []
    for record in records:
        encoded = record["name"].encode("utf-8")
        name_slices.append((len(names_blob), len(encoded)))
        names_blob += encoded

    meta_blob = bytearray(struct.pack("<I", len(records)))
    for record, (name_offset, name_length) in zip(records, name_slices):
        meta_blob += struct.pack(
            "<IB3xIIH2xii",
            record["adcode"],
            record["level"],
            record["parent"],
            name_offset,
            name_length,
            round_half_away(record["lat"] * 1_000_000),
            round_half_away(record["lng"] * 1_000_000),
        )

    # ---- GEOM ----------------------------------------------------------------
    geom_blob = bytearray()
    geom_index = []
    if args.dataset == "mini":
        geom_index = [0] * (len(records) + 1)
    else:
        # SPEC §2.1: only province and district geometry is needed; the city
        # chain is derived from the district's adcode.
        for record in records:
            geom_index.append(len(geom_blob))
            if record["level_name"] == "city":
                continue
            level = levels[record["level_name"]]
            geom_blob += encode_geometry(level.geometries[record["local_index"]], scale)
        geom_index.append(len(geom_blob))
        print(f"\n  geometry   {len(geom_blob) / 1048576:>8.2f} MB")

    # ---- GRID ----------------------------------------------------------------
    grid_width = grid_height = 0
    grids: dict[str, tuple] = {}
    for level_name in ("district", "province"):
        if grid_step is None:
            grids[level_name] = ([], [])
            continue
        elapsed = time.time()
        width, height, runs, mixed = build_grid(
            levels[level_name], grid_step, order[level_name]
        )
        grid_width, grid_height = width, height
        grids[level_name] = (runs, mixed)
        solid_cells = sum(length for _, length, _ in runs)
        candidates = sum(len(c) for _, c in mixed)
        print(
            f"  grid {grid_step}° {level_name:8s} {width}x{height}  "
            f"solid {solid_cells:,} in {len(runs):,} runs  "
            f"mixed {len(mixed):,} (avg {candidates / max(len(mixed), 1):.2f})  "
            f"{time.time() - elapsed:.0f}s"
        )

    def encode_grid(runs, mixed):
        solid_blob = bytearray(struct.pack("<I", len(runs)))
        for start, length, value in runs:
            solid_blob += struct.pack("<III", start, length, value)
        cells_blob = bytearray(struct.pack("<I", len(mixed)))
        ptrs = [0]
        lists_blob = bytearray()
        for _, candidate_list in mixed:
            ptrs.append(ptrs[-1] + len(candidate_list))
        for cell_id, _ in mixed:
            cells_blob += struct.pack("<I", cell_id)
        for _, candidate_list in mixed:
            for record_index in candidate_list:
                lists_blob += struct.pack("<I", record_index)
        return (
            bytes(solid_blob),
            bytes(cells_blob),
            b"".join(struct.pack("<I", p) for p in ptrs),
            bytes(lists_blob),
        )

    d_solid, d_cells, d_ptrs, d_lists = encode_grid(*grids["district"])
    p_solid, p_cells, p_ptrs, p_lists = encode_grid(*grids["province"])

    # ---- assemble ------------------------------------------------------------
    sections = [
        (SECTION_META, bytes(meta_blob)),
        (SECTION_NAMES, bytes(names_blob)),
        (SECTION_GEOM, bytes(geom_blob)),
        (SECTION_GEOM_INDEX, b"".join(struct.pack("<I", o) for o in geom_index)),
        (SECTION_GRID_SOLID, d_solid),
        (SECTION_GRID_MIXED_CELLS, d_cells),
        (SECTION_GRID_MIXED_PTRS, d_ptrs),
        (SECTION_GRID_MIXED_LISTS, d_lists),
        (SECTION_GRID_PROV_SOLID, p_solid),
        (SECTION_GRID_PROV_MIXED_CELLS, p_cells),
        (SECTION_GRID_PROV_MIXED_PTRS, p_ptrs),
        (SECTION_GRID_PROV_MIXED_LISTS, p_lists),
    ]

    data_version = json.loads((DATA_DIR / "DATA_VERSION.json").read_text(encoding="utf-8"))
    data_stamp = int(data_version["fetched_at"].replace("-", ""))

    header_size = 32 + 24 * len(sections)
    offset = (header_size + 7) & ~7
    entries = []
    for section_type, payload in sections:
        entries.append((section_type, zlib.crc32(payload), offset, len(payload)))
        offset = (offset + len(payload) + 7) & ~7

    header = struct.pack(
        "<4sHBBIH2xiiIHH",
        MAGIC,
        FORMAT_VERSION,
        dataset_id,
        precision,
        data_stamp,
        len(sections),
        round_half_away(GRID_ORIGIN_LNG * 1_000_000),
        round_half_away(GRID_ORIGIN_LAT * 1_000_000),
        round_half_away((grid_step or 0) * 1_000_000),
        grid_width,
        grid_height,
    )
    assert len(header) == 32, len(header)

    blob = bytearray(header)
    for section_type, crc, section_offset, length in entries:
        blob += struct.pack("<HHIQQ", section_type, 0, crc, section_offset, length)
    for (_, payload), (_, _, section_offset, _) in zip(sections, entries):
        blob += b"\0" * (section_offset - len(blob))
        blob += payload

    out_path.write_bytes(bytes(blob))
    size = out_path.stat().st_size
    print(f"\n  {out_path.name}  {size / 1048576:.2f} MB  ({time.time() - started:.0f}s)")
    for (section_type, payload), _ in zip(sections, entries):
        if len(payload) > 100_000:
            print(f"    section {section_type}  {len(payload) / 1048576:>6.2f} MB")


if __name__ == "__main__":
    main()
