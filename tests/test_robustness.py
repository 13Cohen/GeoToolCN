"""Robustness: bad inputs, bad files, resource handling.

The conformance suite pins what the library answers; these pin how it fails.
Each test here is a regression for a way the library once failed badly —
a raw ValueError from int(nan), a BufferError from close(), an unbounded
struct.error from a truncated file.
"""

from __future__ import annotations

import gc
import math
import os
import struct

import pytest

import GeoToolCN
from GeoToolCN import GeometryUnavailable, GeoTool, GTCFormatError, distance
from GeoToolCN.core import _DEFAULT_GTC


@pytest.fixture(scope="module")
def geo() -> GeoTool:
    return GeoTool()


@pytest.fixture(scope="module")
def raw() -> bytes:
    with open(_DEFAULT_GTC, "rb") as f:
        return f.read()


# ---------------------------------------------------------------
# Coordinates that are numbers but not positions
# ---------------------------------------------------------------


class TestNonFiniteCoordinates:
    """SPEC §2.1: NaN and ±Inf are outside China, not an error.

    Pandas frames carry NaN routinely, and one bad row must not take the
    whole reverse_batch down with it. JSON cannot express NaN, so the
    conformance suite can never cover this; each port tests it itself.
    """

    @pytest.mark.parametrize(
        "lat,lng",
        [
            (math.nan, 116.4),
            (39.9, math.nan),
            (math.inf, 116.4),
            (39.9, -math.inf),
            (math.nan, math.nan),
        ],
    )
    def test_reverse_is_empty(self, geo: GeoTool, lat: float, lng: float) -> None:
        r = geo.reverse(lat, lng)
        assert (r.province, r.city, r.district) == (None, None, None)
        assert geo.is_in_china(lat, lng) is False
        assert geo.is_in_region(lat, lng, "110000") is False
        assert geo.is_in_region(lat, lng, "110101") is False

    def test_batch_survives_one_bad_row(self, geo: GeoTool) -> None:
        results = geo.reverse_batch([(39.9, 116.4), (math.nan, 116.4), (31.2, 121.5)])
        assert results[0].district is not None
        assert results[1].district is None
        assert results[2].province is not None and "上海" in results[2].province.name


class TestGridRounding:
    def test_point_just_outside_origin_is_outside(self, geo: GeoTool) -> None:
        # SPEC §4.6 says floor. int() truncates toward zero, which would put
        # a point half a step west of the origin in column 0.
        data = geo._data
        lat = data.origin_lat + 10 * data.grid_step
        lng = data.origin_lng - data.grid_step / 2
        assert data.locate(lat, lng) is None
        assert data.locate_province(lat, lng) is None
        assert data.locate(data.origin_lat - data.grid_step / 2, 110.0) is None


# ---------------------------------------------------------------
# distance()
# ---------------------------------------------------------------


class TestDistanceEdgeCases:
    def test_antipodal_does_not_raise(self) -> None:
        # Rounding pushes the haversine term a few ulp past 1 here; the
        # unclamped form raised "math domain error".
        d = distance(15.17, 145.51, -15.17, -34.49)
        assert d == pytest.approx(20015.09, abs=0.5)

    def test_same_point_is_zero(self) -> None:
        assert distance(39.9, 116.4, 39.9, 116.4) == 0.0

    def test_matches_ports_formula(self) -> None:
        # asin(min(1, sqrt(a))), as Node and Go compute it, so all three
        # agree to the last bit rather than merely to the tolerance.
        assert distance(39.9042, 116.4074, 31.2304, 121.4737) == pytest.approx(
            1067.31, abs=0.01
        )


# ---------------------------------------------------------------
# Resource handling
# ---------------------------------------------------------------


def _open_fds() -> int:
    if os.path.isdir("/dev/fd"):
        return len(os.listdir("/dev/fd"))
    pytest.skip("no /dev/fd on this platform")


class TestResourceHandling:
    def test_close_is_idempotent_and_releases_mapping(self) -> None:
        geo = GeoTool()
        assert geo.reverse(39.9, 116.4).district is not None
        geo.close()
        geo.close()
        with pytest.raises(ValueError, match="closed"):
            geo.reverse(39.9, 116.4)

    def test_context_manager(self) -> None:
        with GeoTool() as geo:
            assert geo.get_region("110000") is not None
        with pytest.raises(ValueError, match="closed"):
            geo.reverse(39.9, 116.4)

    def test_instances_do_not_leak_descriptors(self) -> None:
        # Two hundred instances used to hold four hundred descriptors open —
        # the file and the mmap's dup of it — until the GC got round to them.
        gc.collect()
        before = _open_fds()
        for _ in range(50):
            GeoTool().reverse(39.9, 116.4)
        gc.collect()
        assert _open_fds() - before <= 2

    def test_no_resource_warning_when_dropped(self, recwarn) -> None:
        import warnings

        with warnings.catch_warnings():
            warnings.simplefilter("error", ResourceWarning)
            geo = GeoTool()
            geo.reverse(39.9, 116.4)
            del geo
            gc.collect()

    def test_lookups_after_close_fail_loudly(self) -> None:
        geo = GeoTool()
        geo.close()
        with pytest.raises(ValueError):
            geo.is_in_china(39.9, 116.4)


# ---------------------------------------------------------------
# Damaged files
# ---------------------------------------------------------------


def _with_geom_length(raw: bytes, length: int) -> bytes:
    """Rewrite the GEOM section's length in the section table.

    With ``length=0`` this also zeroes the grid step, which is what a real
    ``mini`` build writes — the reader must accept that combination.
    """
    from GeoToolCN._gtc import SECTION_GEOM

    out = bytearray(raw)
    section_count = struct.unpack_from("<H", raw, 12)[0]
    for i in range(section_count):
        base = 32 + 24 * i
        if struct.unpack_from("<H", raw, base)[0] == SECTION_GEOM:
            struct.pack_into("<Q", out, base + 16, length)
    if length == 0:
        struct.pack_into("<I", out, 24, 0)
    return bytes(out)


class TestDamagedFiles:
    @pytest.mark.parametrize("cut", [0, 8, 31, 32, 100, 4096, 500_000])
    def test_truncated_is_a_format_error(self, tmp_path, raw: bytes, cut: int) -> None:
        path = tmp_path / "cut.gtc"
        path.write_bytes(raw[:cut])
        with pytest.raises(GTCFormatError):
            GeoTool(str(path))

    def test_wrong_magic(self, tmp_path, raw: bytes) -> None:
        path = tmp_path / "bad.gtc"
        path.write_bytes(b"NOPE" + raw[4:])
        with pytest.raises(GTCFormatError, match="not a .gtc"):
            GeoTool(str(path))

    def test_section_past_end_of_file(self, tmp_path, raw: bytes) -> None:
        path = tmp_path / "bad.gtc"
        path.write_bytes(_with_geom_length(raw, 1 << 40))
        with pytest.raises(GTCFormatError, match="outside the file"):
            GeoTool(str(path))

    def test_checksum_is_verified_on_request(self, tmp_path, raw: bytes) -> None:
        # Flip one byte in the GEOM blob (well past the section table).
        out = bytearray(raw)
        out[len(raw) // 2] ^= 0xFF
        path = tmp_path / "flipped.gtc"
        path.write_bytes(bytes(out))
        GeoTool(str(path))  # loads: the default trusts the file
        with pytest.raises(GTCFormatError, match="checksum"):
            GeoTool(str(path), verify_checksums=True)

    def test_directory_without_a_gtc(self, tmp_path) -> None:
        with pytest.raises(FileNotFoundError, match="china.full.gtc"):
            GeoTool(str(tmp_path))

    def test_directory_with_a_lite_file_is_accepted(self, tmp_path, raw: bytes) -> None:
        (tmp_path / "china.lite.gtc").write_bytes(raw)
        assert GeoTool(str(tmp_path)).get_region("110000") is not None

    def test_no_geometry_raises_geometry_unavailable(self, tmp_path, raw: bytes) -> None:
        # A "mini" view of the full file: GEOM length zeroed. Name and adcode
        # lookups still work; anything needing geometry says so.
        path = tmp_path / "mini.gtc"
        path.write_bytes(_with_geom_length(raw, 0))
        geo = GeoTool(str(path))
        assert geo.get_region("110000").name == "北京市"
        assert geo.search("深圳市")[0].code == "440300"
        with pytest.raises(GeometryUnavailable):
            geo.reverse(39.9, 116.4)
        with pytest.raises(GeometryUnavailable):
            geo.is_in_china(39.9, 116.4)


class TestProcessAndThreadUse:
    def test_pickle_round_trip(self) -> None:
        import pickle

        geo = GeoTool()
        clone = pickle.loads(pickle.dumps(geo))
        assert clone.reverse(39.9, 116.4).district.code == "110101"
        assert clone is not geo

    def test_spawned_process_can_use_a_pickled_instance(self) -> None:
        import multiprocessing

        ctx = multiprocessing.get_context("spawn")
        geo = GeoTool()
        coords = [(39.9, 116.4), (31.2, 121.5)]
        with ctx.Pool(1) as pool:
            results = pool.starmap(geo.reverse, coords)
        assert results == [geo.reverse(lat, lng) for lat, lng in coords]

    def test_shared_instance_is_created_once_under_contention(self) -> None:
        import threading

        import GeoToolCN as pkg

        saved = pkg._instance
        pkg._instance = None
        try:
            seen = []
            barrier = threading.Barrier(16)

            def worker():
                barrier.wait()
                seen.append(pkg._get_instance())

            threads = [threading.Thread(target=worker) for _ in range(16)]
            for t in threads:
                t.start()
            for t in threads:
                t.join()
            assert len({id(g) for g in seen}) == 1
        finally:
            pkg._instance = saved


class TestPublicExceptions:
    def test_exported_at_top_level(self) -> None:
        assert GeoToolCN.GTCFormatError is GTCFormatError
        assert GeoToolCN.GeometryUnavailable is GeometryUnavailable
        assert "GTCFormatError" in GeoToolCN.__all__
        assert "GeometryUnavailable" in GeoToolCN.__all__
