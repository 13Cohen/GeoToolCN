"""Structural invariants — the language-neutral correctness contract.

Unlike hand-picked example tests, these assert *properties* that must hold for
every administrative region.  Two consequences:

* **Coverage.** ``INV-01`` alone produces one assertion per district, taking
  adcode coverage from the ~0.5% that the example-based suites reach to 100%.
* **Durability.** No golden values are baked in, so a DataV data refresh does
  not invalidate them.

Every implementation of the GeoToolCN API — in any language — must satisfy all
of these.  See ``docs/RFC-002-testing-and-acceptance.md`` §L1.

Each test collects *all* violations before asserting, so a failure report names
every offending region rather than aborting at the first one.
"""
from __future__ import annotations

import math
import random

import pytest

from GeoToolCN import (
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

# Municipalities (直辖市) and SARs (特别行政区): districts sit directly under
# the province, and the city node reuses the province code.
MERGED_PREFIXES = frozenset({"11", "12", "31", "50", "81", "82"})

LEVELS = ("province", "city", "district")

# Sample sizes for the invariants that need random points rather than
# exhaustive enumeration.
RANDOM_SAMPLE = 2000
COORD_SAMPLE = 10000
BATCH_SAMPLE = 500

# Maximum acceptable round-trip error per conversion pair, in metres.
# gcj02_to_wgs84 is a single-step subtraction, not an iterative inverse, so its
# round trip is inherently lossy: measured median 0.64 m, p99 3.2 m, max 4.75 m
# over 20k points.  The bd09 pair has a near-exact inverse and stays under 0.25 m.
# These bound the published algorithm; tightening them means changing it.
COORD_ROUNDTRIP_TOLERANCE_M = {
    "wgs84<->gcj02": 6.0,
    "gcj02<->bd09": 0.5,
    "wgs84<->bd09": 6.0,
}

_MAX_REPORTED = 15


@pytest.fixture(scope="module")
def geo() -> GeoTool:
    return GeoTool()


@pytest.fixture(scope="module")
def regions(geo: GeoTool) -> dict[str, list]:
    return {level: geo.list_regions(level) for level in LEVELS}


@pytest.fixture(scope="module")
def city_codes(regions: dict[str, list]) -> frozenset[str]:
    return frozenset(r.code for r in regions["city"])


def expected_parent_city(district_code: str, city_codes: frozenset[str]) -> str | None:
    """Resolve a district's parent city from adcode structure alone.

    The naive ``adcode[:4] + "00"`` rule is *wrong* for the 30 province-directly-
    governed county-level divisions (省直辖县级行政区) in adcode blocks 4190
    (济源), 4290 (仙桃/潜江/天门/神农架), 4690 (海南) and 6590 (新疆) — it yields
    codes such as ``419000`` that name no real division.  Those divisions appear
    in the city layer under their own code, so fall back to that.
    """
    prefix2 = district_code[:2]
    if prefix2 in MERGED_PREFIXES:
        return prefix2 + "0000"
    by_prefix = district_code[:4] + "00"
    if by_prefix in city_codes:
        return by_prefix
    if district_code in city_codes:
        return district_code
    return None


def _fail(violations: list[str], total: int, label: str) -> None:
    """Assert *violations* is empty, reporting a bounded sample on failure."""
    if not violations:
        return
    shown = "\n  ".join(violations[:_MAX_REPORTED])
    more = (
        f"\n  ... and {len(violations) - _MAX_REPORTED} more"
        if len(violations) > _MAX_REPORTED
        else ""
    )
    pytest.fail(
        f"{label}: {len(violations)}/{total} violations\n  {shown}{more}",
        pytrace=False,
    )


def _random_points(n: int, seed: int) -> list[tuple[float, float]]:
    rng = random.Random(seed)
    return [(rng.uniform(3.0, 54.0), rng.uniform(73.0, 136.0)) for _ in range(n)]


# ---------------------------------------------------------------
# INV-01 .. INV-03 — reverse geocoding self-consistency
# ---------------------------------------------------------------


class TestReverseInvariants:
    def test_inv01_representative_point_round_trips(
        self, geo: GeoTool, regions: dict[str, list]
    ) -> None:
        """INV-01: reversing a region's own representative point returns it."""
        districts = regions["district"]
        violations = [
            f"{r.name}({r.code}) at ({r.latitude},{r.longitude}) -> "
            f"{result.district.code if result.district else None}"
            for r in districts
            for result in [geo.reverse(r.latitude, r.longitude)]
            if result.district is None or result.district.code != r.code
        ]
        _fail(violations, len(districts), "INV-01 representative point round-trip")

    def test_inv02_province_district_prefix_agree(
        self, geo: GeoTool, regions: dict[str, list]
    ) -> None:
        """INV-02: province and district must share the same adcode prefix.

        A result pairing a district with a province it does not belong to — or
        omitting the province while naming a district — is internally
        inconsistent regardless of what the boundary polygons say.
        """
        districts = regions["district"]
        violations = []
        for r in districts:
            result = geo.reverse(r.latitude, r.longitude)
            if result.district is None:
                continue
            if result.province is None:
                violations.append(
                    f"{r.name}({r.code}): district found but province is None"
                )
            elif result.province.code[:2] != result.district.code[:2]:
                violations.append(
                    f"{r.name}({r.code}): province={result.province.code} "
                    f"district={result.district.code} prefix mismatch"
                )
        _fail(violations, len(districts), "INV-02 province/district prefix")

    def test_inv03_city_is_district_parent(
        self, geo: GeoTool, regions: dict[str, list], city_codes: frozenset[str]
    ) -> None:
        """INV-03: the returned city must be the district's structural parent."""
        districts = regions["district"]
        violations = []
        for r in districts:
            result = geo.reverse(r.latitude, r.longitude)
            if result.district is None:
                continue
            expected = expected_parent_city(result.district.code, city_codes)
            actual = result.city.code if result.city else None
            if actual != expected:
                violations.append(
                    f"{r.name}({r.code}): city={actual} but parent of "
                    f"{result.district.code} is {expected}"
                )
        _fail(violations, len(districts), "INV-03 city is district parent")


class TestReverseInvariantsNearBoundaries:
    """INV-02/INV-03 again, on points scattered around region boundaries.

    Representative points sit deep inside their own polygon, so they never
    exercise the places where the province, city and district layers disagree
    with each other.  Every hierarchy contradiction found while designing this
    suite — 包头市 claiming a point inside 乌拉特前旗, 苏州市 claiming one inside
    秀洲区 — was reachable only by perturbing off the representative point.
    """

    @pytest.fixture(scope="class")
    def perturbed(self, regions: dict[str, list]) -> list[tuple[float, float]]:
        rng = random.Random(2)
        return [
            (r.latitude + rng.uniform(-0.3, 0.3), r.longitude + rng.uniform(-0.3, 0.3))
            for r in regions["district"]
        ]

    def test_inv02_prefix_agrees_near_boundaries(
        self, geo: GeoTool, perturbed: list[tuple[float, float]]
    ) -> None:
        violations = []
        for lat, lng in perturbed:
            result = geo.reverse(lat, lng)
            if result.district is None:
                continue
            if result.province is None:
                violations.append(
                    f"({lat:.5f},{lng:.5f}): district={result.district.code} "
                    f"but province is None"
                )
            elif result.province.code[:2] != result.district.code[:2]:
                violations.append(
                    f"({lat:.5f},{lng:.5f}): province={result.province.code} "
                    f"district={result.district.code} prefix mismatch"
                )
        _fail(violations, len(perturbed), "INV-02 (boundary) province/district prefix")

    def test_inv03_city_is_parent_near_boundaries(
        self,
        geo: GeoTool,
        perturbed: list[tuple[float, float]],
        city_codes: frozenset[str],
    ) -> None:
        violations = []
        for lat, lng in perturbed:
            result = geo.reverse(lat, lng)
            if result.district is None:
                continue
            expected = expected_parent_city(result.district.code, city_codes)
            actual = result.city.code if result.city else None
            if actual != expected:
                violations.append(
                    f"({lat:.5f},{lng:.5f}): city={actual} but parent of "
                    f"{result.district.code} is {expected}"
                )
        _fail(violations, len(perturbed), "INV-03 (boundary) city is district parent")


# ---------------------------------------------------------------
# INV-04 .. INV-07 — lookup / containment / search consistency
# ---------------------------------------------------------------


class TestLookupInvariants:
    def test_inv04_region_contains_own_representative_point(
        self, geo: GeoTool, regions: dict[str, list]
    ) -> None:
        """INV-04: is_in_region is True for a region's own representative point."""
        violations = []
        total = 0
        for level in LEVELS:
            for r in regions[level]:
                total += 1
                if not geo.is_in_region(r.latitude, r.longitude, r.code):
                    violations.append(f"{r.name}({r.code}, {level}) excludes its own point")
        _fail(violations, total, "INV-04 self-containment")

    def test_inv05_lookup_adcode_round_trips(
        self, geo: GeoTool, regions: dict[str, list]
    ) -> None:
        """INV-05: lookup_adcode(x) resolves back to x at its own level."""
        violations = []
        total = 0
        for level in LEVELS:
            for r in regions[level]:
                total += 1
                result = geo.lookup_adcode(r.code)
                if result is None:
                    violations.append(f"{r.name}({r.code}, {level}): lookup returned None")
                    continue
                resolved = getattr(result, level)
                if resolved is None or resolved.code != r.code:
                    violations.append(
                        f"{r.name}({r.code}, {level}) -> "
                        f"{resolved.code if resolved else None}"
                    )
        _fail(violations, total, "INV-05 lookup_adcode round-trip")

    def test_inv06_codes_unique_and_retrievable(
        self, geo: GeoTool, regions: dict[str, list]
    ) -> None:
        """INV-06: every listed adcode is unique within its level and findable."""
        violations = []
        total = 0
        for level in LEVELS:
            seen: set[str] = set()
            for r in regions[level]:
                total += 1
                if r.code in seen:
                    violations.append(f"duplicate adcode {r.code} in level {level}")
                seen.add(r.code)
                if geo.get_region(r.code) is None:
                    violations.append(f"{r.name}({r.code}, {level}): get_region returned None")
        _fail(violations, total, "INV-06 adcode uniqueness / retrievability")

    def test_inv07_exact_name_search_finds_region(
        self, geo: GeoTool, regions: dict[str, list]
    ) -> None:
        """INV-07: searching a region's exact name returns that region."""
        violations = []
        total = 0
        for level in LEVELS:
            for r in regions[level]:
                total += 1
                try:
                    results = geo.search(r.name, level=level)
                except Exception as exc:  # noqa: BLE001 - surfaced as a violation
                    violations.append(f"{r.name}({r.code}): search raised {type(exc).__name__}: {exc}")
                    continue
                if r.code not in {x.code for x in results}:
                    violations.append(f"{r.name}({r.code}, {level}) not in its own search results")
        _fail(violations, total, "INV-07 exact-name search")


# ---------------------------------------------------------------
# INV-08 — coordinate conversion (pure math, no data dependency)
# ---------------------------------------------------------------


class TestCoordInvariants:
    def test_inv08_conversions_round_trip(self) -> None:
        """INV-08: every conversion pair round-trips within 1 m."""
        violations = []
        pairs = [
            ("wgs84<->gcj02", wgs84_to_gcj02, gcj02_to_wgs84),
            ("gcj02<->bd09", gcj02_to_bd09, bd09_to_gcj02),
            ("wgs84<->bd09", wgs84_to_bd09, bd09_to_wgs84),
        ]
        points = _random_points(COORD_SAMPLE, seed=8)
        for label, forward, backward in pairs:
            for lat, lng in points:
                # These take (lng, lat).  Feeding them (lat, lng) makes the test
                # vacuous rather than failing: the swapped longitude lands outside
                # the China bounding box, so the value is returned untouched and
                # every round-trip is trivially exact.
                f_lng, f_lat = forward(lng, lat)
                b_lng, b_lat = backward(f_lng, f_lat)
                error_m = distance(lat, lng, b_lat, b_lng) * 1000
                if error_m > COORD_ROUNDTRIP_TOLERANCE_M[label] or math.isnan(error_m):
                    violations.append(f"{label} at ({lat:.5f},{lng:.5f}): {error_m:.3f} m")
        _fail(violations, COORD_SAMPLE * len(pairs), "INV-08 conversion round-trip")

    def test_inv08_outside_china_passes_through(self) -> None:
        """INV-08b: GCJ-02 offset is not applied outside China."""
        violations = []
        outside = [(35.6762, 139.6503), (40.7128, -74.0060), (-33.8688, 151.2093)]
        for lat, lng in outside:
            got_lng, got_lat = wgs84_to_gcj02(lng, lat)
            if (got_lng, got_lat) != (lng, lat):
                violations.append(f"({lat},{lng}) -> ({got_lat},{got_lng})")
        _fail(violations, len(outside), "INV-08b out-of-China pass-through")


# ---------------------------------------------------------------
# INV-09 .. INV-10 — administrative tree agrees with the geo layers
# ---------------------------------------------------------------


class TestTreeInvariants:
    def test_inv09_tree_leaves_match_district_layer(self, regions: dict[str, list]) -> None:
        """INV-09: the tree's leaf codes are exactly the district layer's codes."""
        leaves = {
            district["value"]
            for province in get_administrative_tree()
            for city in province["children"]
            for district in city.get("children", [])
        }
        listed = {r.code for r in regions["district"]}
        violations = [f"only in tree: {c}" for c in sorted(leaves - listed)]
        violations += [f"only in district layer: {c}" for c in sorted(listed - leaves)]
        _fail(violations, len(listed | leaves), "INV-09 tree/district agreement")

    def test_inv09b_each_district_appears_once(self) -> None:
        """INV-09b: no district is reachable by two different paths.

        Comparing code *sets* (INV-09) misses duplication entirely — it passed
        while every one of 海南's 15 county-level cities was listed under each
        of the other 14, inflating the tree from 2874 leaves to 3186.
        """
        occurrences: dict[str, list[str]] = {}
        for province in get_administrative_tree():
            for city in province["children"]:
                for district in city.get("children", []):
                    occurrences.setdefault(district["value"], []).append(city["value"])
        violations = [
            f"{code} appears under {len(parents)} cities: {sorted(parents)[:5]}"
            for code, parents in sorted(occurrences.items())
            if len(parents) > 1
        ]
        _fail(violations, len(occurrences), "INV-09b district appears once")

    def test_inv10_reverse_path_exists_in_tree(
        self, geo: GeoTool, regions: dict[str, list]
    ) -> None:
        """INV-10: a fully-resolved reverse result is a real path in the tree."""
        paths = {
            (province["value"], city["value"], district["value"])
            for province in get_administrative_tree()
            for city in province["children"]
            for district in city.get("children", [])
        }
        violations = []
        total = 0
        for r in regions["district"]:
            result = geo.reverse(r.latitude, r.longitude)
            if not (result.province and result.city and result.district):
                continue
            total += 1
            path = (result.province.code, result.city.code, result.district.code)
            if path not in paths:
                violations.append(f"{r.name}({r.code}): path {path} absent from tree")
        _fail(violations, total, "INV-10 reverse path in tree")


# ---------------------------------------------------------------
# INV-11 .. INV-12 — cross-API agreement
# ---------------------------------------------------------------


class TestCrossApiInvariants:
    def test_inv11_is_in_china_agrees_with_reverse(self, geo: GeoTool) -> None:
        """INV-11: is_in_china is equivalent to reverse() resolving a province."""
        points = _random_points(RANDOM_SAMPLE, seed=11)
        violations = [
            f"({lat:.5f},{lng:.5f}): is_in_china={inside} but province="
            f"{geo.reverse(lat, lng).province}"
            for lat, lng in points
            for inside in [geo.is_in_china(lat, lng)]
            if inside != (geo.reverse(lat, lng).province is not None)
        ]
        _fail(violations, RANDOM_SAMPLE, "INV-11 is_in_china vs reverse")

    def test_inv12_batch_matches_serial(self, geo: GeoTool, regions: dict[str, list]) -> None:
        """INV-12: reverse_batch is indistinguishable from a reverse() loop."""
        rng = random.Random(12)
        sample = rng.sample(regions["district"], min(BATCH_SAMPLE, len(regions["district"])))
        coords = [(r.latitude, r.longitude) for r in sample]
        batched = geo.reverse_batch(coords)
        violations = []
        for (lat, lng), got in zip(coords, batched):
            want = geo.reverse(lat, lng)
            for level in LEVELS:
                a = getattr(want, level)
                b = getattr(got, level)
                if (a.code if a else None) != (b.code if b else None):
                    violations.append(
                        f"({lat:.5f},{lng:.5f}) {level}: serial="
                        f"{a.code if a else None} batch={b.code if b else None}"
                    )
        _fail(violations, len(coords), "INV-12 batch vs serial")
