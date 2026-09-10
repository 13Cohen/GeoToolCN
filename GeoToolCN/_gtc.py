"""Reader for the .gtc binary — standard library only.

This is the reference for every port: the same ~600 lines in another language
produce the same answers, because the expensive work already happened at build
time.  A lookup is a binary search in a run-length table, and only when that
misses does any geometry get touched — about 23% of queries, against an average
of 2 candidate polygons.

Format: SPEC.md §4.  Behaviour: SPEC.md §2 and §3.
"""
from __future__ import annotations

import mmap
import struct
import zlib
from array import array
from bisect import bisect_left, bisect_right

MAGIC = b"GTCN"
SUPPORTED_FORMAT_VERSION = 1

LEVELS = ("province", "city", "district")

SECTION_META = 1
SECTION_NAMES = 2
SECTION_GEOM = 3
SECTION_GEOM_INDEX = 4
SECTION_GRID_SOLID = 5
SECTION_GRID_MIXED_CELLS = 6
SECTION_GRID_MIXED_PTRS = 7
SECTION_GRID_MIXED_LISTS = 8
SECTION_GRID_PROV_SOLID = 9
SECTION_GRID_PROV_MIXED_CELLS = 10
SECTION_GRID_PROV_MIXED_PTRS = 11
SECTION_GRID_PROV_MIXED_LISTS = 12

_META_RECORD = struct.Struct("<IB3xIIH2xii")
_META_SIZE = _META_RECORD.size


class GTCFormatError(Exception):
    """The file is not a readable .gtc."""


class GeometryUnavailable(Exception):
    """A geometry-dependent call was made against a dataset without geometry."""


def _u32_array(view: memoryview) -> array:
    """Materialise a little-endian u32 table.

    ``frombytes`` is a memcpy, so this stays sub-millisecond even for the
    ~500k entries the full grid index carries.
    """
    out = array("I")
    out.frombytes(view)
    if struct.pack("<I", 1) != struct.pack("=I", 1):  # pragma: no cover - big endian
        out.byteswap()
    return out


class GTCData:
    """Memory-mapped .gtc file with the lookup tables it needs."""

    def __init__(self, path: str, *, verify_checksums: bool = False) -> None:
        self._file = open(path, "rb")
        self._mm = mmap.mmap(self._file.fileno(), 0, access=mmap.ACCESS_READ)
        view = memoryview(self._mm)

        if bytes(view[:4]) != MAGIC:
            raise GTCFormatError(f"{path!r} is not a .gtc file")
        (
            format_version,
            self.dataset,
            self.precision,
            self.data_version,
            section_count,
            origin_lng,
            origin_lat,
            grid_step,
            self.grid_width,
            self.grid_height,
        ) = struct.unpack_from("<HBBIH2xiiIHH", view, 4)

        if format_version != SUPPORTED_FORMAT_VERSION:
            raise GTCFormatError(
                f"format version {format_version} is not supported "
                f"(this build reads version {SUPPORTED_FORMAT_VERSION})"
            )

        self.scale = 10 ** self.precision
        self.origin_lng = origin_lng / 1_000_000
        self.origin_lat = origin_lat / 1_000_000
        self.grid_step = grid_step / 1_000_000

        sections: dict[int, memoryview] = {}
        for i in range(section_count):
            section_type, _, crc, offset, length = struct.unpack_from(
                "<HHIQQ", view, 32 + 24 * i
            )
            payload = view[offset : offset + length]
            if verify_checksums and zlib.crc32(payload) != crc:
                raise GTCFormatError(f"section {section_type} failed its checksum")
            sections[section_type] = payload

        self._names = sections[SECTION_NAMES]
        self._meta = sections[SECTION_META]
        self.record_count = struct.unpack_from("<I", self._meta, 0)[0]

        self._geom = sections[SECTION_GEOM]
        self._geom_index = _u32_array(sections[SECTION_GEOM_INDEX])
        self.has_geometry = len(self._geom) > 0

        self._district_grid = self._load_grid(
            sections,
            SECTION_GRID_SOLID,
            SECTION_GRID_MIXED_CELLS,
            SECTION_GRID_MIXED_PTRS,
            SECTION_GRID_MIXED_LISTS,
        )
        self._province_grid = self._load_grid(
            sections,
            SECTION_GRID_PROV_SOLID,
            SECTION_GRID_PROV_MIXED_CELLS,
            SECTION_GRID_PROV_MIXED_PTRS,
            SECTION_GRID_PROV_MIXED_LISTS,
        )

        self._geometry_cache: dict[int, tuple] = {}
        self._build_indexes()

    @staticmethod
    def _load_grid(sections, solid_type, cells_type, ptrs_type, lists_type):
        solid = sections[solid_type]
        run_count = struct.unpack_from("<I", solid, 0)[0]
        flat = _u32_array(solid[4 : 4 + 12 * run_count])
        cells_section = sections[cells_type]
        mixed_count = struct.unpack_from("<I", cells_section, 0)[0]
        return (
            flat[0::3],                                              # run start
            flat[1::3],                                              # run length
            flat[2::3],                                              # run value
            _u32_array(cells_section[4 : 4 + 4 * mixed_count]),      # mixed cells
            _u32_array(sections[ptrs_type]),                         # mixed ptrs
            _u32_array(sections[lists_type]),                        # mixed lists
        )

    # ------------------------------------------------------------------
    # Metadata
    # ------------------------------------------------------------------

    def _build_indexes(self) -> None:
        self.adcodes: list[str] = []
        self.levels: list[int] = []
        self.parents: list[str | None] = []
        self.names: list[str] = []
        self.lats: list[float] = []
        self.lngs: list[float] = []
        self.by_code: dict[str, int] = {}
        self.by_name: dict[str, list[int]] = {}
        self.level_ranges: dict[str, tuple[int, int]] = {}

        offset = 4
        for _ in range(self.record_count):
            adcode, level, parent, name_offset, name_length, lat, lng = (
                _META_RECORD.unpack_from(self._meta, offset)
            )
            offset += _META_SIZE
            code = f"{adcode:06d}"
            index = len(self.adcodes)
            self.adcodes.append(code)
            self.levels.append(level)
            self.parents.append(f"{parent:06d}" if parent else None)
            name = bytes(self._names[name_offset : name_offset + name_length]).decode(
                "utf-8"
            )
            self.names.append(name)
            self.lats.append(lat / 1_000_000)
            self.lngs.append(lng / 1_000_000)
            self.by_code.setdefault(code, index)
            self.by_name.setdefault(name, []).append(index)

        # Records are sorted by (level, adcode), so each level is contiguous.
        for level_id, level_name in enumerate(LEVELS):
            start = bisect_left(self.levels, level_id)
            end = bisect_right(self.levels, level_id)
            self.level_ranges[level_name] = (start, end)

    def index_of(self, code: str, level: str | None = None) -> int | None:
        index = self.by_code.get(code)
        if index is None:
            return None
        if level is not None and self.levels[index] != LEVELS.index(level):
            # A code can exist at two levels (东莞市 is both city and district).
            start, end = self.level_ranges[level]
            for i in range(start, end):
                if self.adcodes[i] == code:
                    return i
            return None
        return index

    # ------------------------------------------------------------------
    # Geometry
    # ------------------------------------------------------------------

    @staticmethod
    def _read_uvarint(buf, pos: int) -> tuple[int, int]:
        result = shift = 0
        while True:
            byte = buf[pos]
            pos += 1
            result |= (byte & 0x7F) << shift
            if not byte & 0x80:
                return result, pos
            shift += 7

    def _read_svarint(self, buf, pos: int) -> tuple[int, int]:
        value, pos = self._read_uvarint(buf, pos)
        return (value >> 1) ^ -(value & 1), pos

    def geometry(self, index: int):
        """Decode one region's polygons, caching the result.

        Decoding is deferred because most lookups never need it: a solid grid
        cell answers outright, and the ~1M vertices in the full dataset would
        otherwise cost seconds to parse up front.
        """
        cached = self._geometry_cache.get(index)
        if cached is not None:
            return cached

        start = self._geom_index[index]
        end = self._geom_index[index + 1]
        if start == end:
            self._geometry_cache[index] = None
            return None

        buf = self._geom
        bbox = struct.unpack_from("<4i", buf, start)
        pos = start + 16
        polygon_count, pos = self._read_uvarint(buf, pos)
        polygons = []
        for _ in range(polygon_count):
            ring_count, pos = self._read_uvarint(buf, pos)
            rings = []
            for _ in range(ring_count):
                point_count, pos = self._read_uvarint(buf, pos)
                xs = array("d", bytes(8 * point_count))
                ys = array("d", bytes(8 * point_count))
                x = y = 0
                for i in range(point_count):
                    dx, pos = self._read_svarint(buf, pos)
                    dy, pos = self._read_svarint(buf, pos)
                    x += dx
                    y += dy
                    xs[i] = x
                    ys[i] = y
                rings.append((xs, ys))
            polygons.append(rings)

        decoded = (bbox, polygons)
        self._geometry_cache[index] = decoded
        return decoded

    @staticmethod
    def _point_in_ring(xs: array, ys: array, x: float, y: float) -> bool:
        """Even-odd ray casting, exactly as SPEC §3.3 defines it."""
        inside = False
        n = len(xs)
        j = n - 1
        for i in range(n):
            yi = ys[i]
            yj = ys[j]
            if (yi > y) != (yj > y):
                if x < xs[i] + (y - yi) * (xs[j] - xs[i]) / (yj - yi):
                    inside = not inside
            j = i
        return inside

    def contains(self, index: int, qx: float, qy: float) -> bool:
        decoded = self.geometry(index)
        if decoded is None:
            return False
        bbox, polygons = decoded
        if not (bbox[0] <= qx <= bbox[2] and bbox[1] <= qy <= bbox[3]):
            return False
        for rings in polygons:
            outer_xs, outer_ys = rings[0]
            if self._point_in_ring(outer_xs, outer_ys, qx, qy):
                for hole_xs, hole_ys in rings[1:]:
                    if self._point_in_ring(hole_xs, hole_ys, qx, qy):
                        break
                else:
                    return True
        return False

    # ------------------------------------------------------------------
    # Grid lookup
    # ------------------------------------------------------------------

    def _locate_in(self, grid, lat: float, lng: float) -> int | None:
        if not self.has_geometry:
            raise GeometryUnavailable(
                "this dataset carries no geometry; use a lite or full .gtc"
            )
        col = int((lng - self.origin_lng) / self.grid_step)
        row = int((lat - self.origin_lat) / self.grid_step)
        if not (0 <= col < self.grid_width and 0 <= row < self.grid_height):
            return None
        cell_id = row * self.grid_width + col
        run_start, run_length, run_value, mixed_cells, mixed_ptrs, mixed_lists = grid

        i = bisect_right(run_start, cell_id) - 1
        if i >= 0 and run_start[i] <= cell_id < run_start[i] + run_length[i]:
            return run_value[i]

        i = bisect_left(mixed_cells, cell_id)
        if i >= len(mixed_cells) or mixed_cells[i] != cell_id:
            return None

        qx = lng * self.scale
        qy = lat * self.scale
        # Candidates were written in ascending adcode order (SPEC §3.4).
        for slot in range(mixed_ptrs[i], mixed_ptrs[i + 1]):
            index = mixed_lists[slot]
            if self.contains(index, qx, qy):
                return index
        return None

    def locate(self, lat: float, lng: float) -> int | None:
        """Record index of the district containing the point, or None."""
        return self._locate_in(self._district_grid, lat, lng)

    def locate_province(self, lat: float, lng: float) -> int | None:
        """Record index of the province containing the point, or None.

        Needed wherever no district covers the point: Taiwan is published at
        province level only, and coastal gaps leave slivers between districts.
        """
        return self._locate_in(self._province_grid, lat, lng)

    def close(self) -> None:
        self._mm.close()
        self._file.close()
