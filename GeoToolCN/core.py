"""GeoTool backed by the .gtc binary — standard library only.

Behaviourally identical to the geopandas implementation it replaces, minus the
divergences registered in ``conformance/known-divergences.yaml``.  See SPEC.md
§2 for the contract each method implements.
"""
from __future__ import annotations

import os
from dataclasses import dataclass
from typing import Sequence

from ._gtc import LEVELS, GTCData
from ._hierarchy import MERGED_PREFIXES

_DEFAULT_DATA_DIR = os.path.join(os.path.dirname(__file__), "data")
_DEFAULT_GTC = os.path.join(_DEFAULT_DATA_DIR, "china.full.gtc")


@dataclass
class Region:
    """A single administrative region."""

    name: str
    code: str
    level: str
    latitude: float | None = None
    longitude: float | None = None


@dataclass
class ReverseResult:
    """Result of a reverse-geocode lookup for one coordinate."""

    province: Region | None = None
    city: Region | None = None
    district: Region | None = None


class GeoTool:
    """Offline geocoding toolkit for Chinese administrative regions.

    Parameters
    ----------
    data_dir : str, optional
        Path to a ``.gtc`` file, or a directory containing one.  Defaults to
        the bundled dataset.  For compatibility the parameter keeps its old
        name; a directory of GeoJSON is no longer accepted (see
        ``MIGRATION_v3.md``).
    """

    def __init__(self, data_dir: str | None = None) -> None:
        path = data_dir or _DEFAULT_GTC
        if os.path.isdir(path):
            candidate = os.path.join(path, "china.full.gtc")
            if not os.path.exists(candidate):
                raise FileNotFoundError(
                    f"no china.full.gtc in {path!r}. Version 3 reads a .gtc "
                    f"binary rather than a directory of GeoJSON; build one with "
                    f"`python pipeline/build_gtc.py`."
                )
            path = candidate
        self._data = GTCData(path)

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    def _region(self, index: int) -> Region:
        data = self._data
        return Region(
            name=data.names[index],
            code=data.adcodes[index],
            level=LEVELS[data.levels[index]],
            latitude=data.lats[index],
            longitude=data.lngs[index],
        )

    def _region_by_code(self, code: str, level: str) -> Region | None:
        index = self._data.index_of(code, level)
        return self._region(index) if index is not None else None

    @staticmethod
    def _province_as_city(province: Region) -> Region:
        """Municipalities and SARs report the province as their city."""
        return Region(
            name=province.name,
            code=province.code,
            level="city",
            latitude=province.latitude,
            longitude=province.longitude,
        )

    def _chain_from_district(self, index: int) -> ReverseResult:
        """SPEC §2.1: derive the upper levels from the district's adcode.

        Testing each layer independently produces contradictions, because the
        source layers overlap and disagree — see SPEC §2.1 and the DIV-001..003
        entries in the divergence registry.
        """
        district = self._region(index)
        province_code = district.code[:2] + "0000"
        province = self._region_by_code(province_code, "province")

        parent = self._data.parents[index]
        if parent is None:
            city = None
        elif parent == province_code:
            city = self._province_as_city(province) if province else None
        else:
            city = self._region_by_code(parent, "city")

        return ReverseResult(province=province, city=city, district=district)

    # ------------------------------------------------------------------
    # Reverse geocoding
    # ------------------------------------------------------------------

    def reverse(self, lat: float, lng: float) -> ReverseResult:
        """Look up the administrative region for a coordinate.

        Parameters
        ----------
        lat : float
            Latitude (WGS-84).
        lng : float
            Longitude (WGS-84).

        Returns
        -------
        ReverseResult
        """
        index = self._data.locate(lat, lng)
        if index is not None:
            return self._chain_from_district(index)

        # No district covers the point — Taiwan is published at province level
        # only, and coastal gaps leave slivers between districts.  Fall back to
        # the province grid.  The city stays empty because the .gtc carries no
        # city geometry (DIV-101, measured at 0.023% of points).
        province_index = self._data.locate_province(lat, lng)
        if province_index is None:
            return ReverseResult()
        province = self._region(province_index)
        city = (
            self._province_as_city(province)
            if province.code[:2] in MERGED_PREFIXES
            else None
        )
        return ReverseResult(province=province, city=city, district=None)

    def reverse_batch(
        self, coords: Sequence[tuple[float, float]]
    ) -> list[ReverseResult]:
        """Reverse-geocode many coordinates.

        Parameters
        ----------
        coords : sequence of (lat, lng) tuples

        Returns
        -------
        list[ReverseResult]
        """
        return [self.reverse(lat, lng) for lat, lng in coords]

    # ------------------------------------------------------------------
    # Forward geocoding / search
    # ------------------------------------------------------------------

    def search(
        self,
        query: str,
        *,
        level: str | None = None,
        province: str | None = None,
        city: str | None = None,
        fuzzy: bool = True,
        regex: bool = False,
    ) -> list[Region]:
        """Search for regions by name or adcode.

        Parameters
        ----------
        query : str
            Region name (e.g. ``"深圳市"``) or adcode (e.g. ``"440300"``).
        level : str, optional
            Restrict to ``"province"``, ``"city"``, or ``"district"``.
        province : str, optional
            Filter results to those within this province (name or adcode).
        city : str, optional
            Filter results to those within this city (name or adcode).
        fuzzy : bool
            If *True* (default), also match regions whose name *contains*
            the query when no exact match is found.
        regex : bool
            Treat *query* as a regular expression during fuzzy matching.
            Defaults to *False* (plain substring).

        Returns
        -------
        list[Region]
        """
        data = self._data
        levels = [level] if level else list(LEVELS)
        matches: list[int] = []

        for level_name in levels:
            start, end = data.level_ranges[level_name]
            if query.isdigit():
                matches += [i for i in range(start, end) if data.adcodes[i] == query]
                continue
            exact = [i for i in data.by_name.get(query, ()) if start <= i < end]
            if exact:
                matches += exact
            elif fuzzy:
                matches += self._fuzzy_match(query, start, end, regex)

        regions = [self._region(i) for i in matches]
        if province is not None:
            regions = self._filter_by_parent(regions, "province", province)
        if city is not None:
            regions = self._filter_by_parent(regions, "city", city)

        regions.sort(key=lambda r: (LEVELS.index(r.level), r.code))
        return regions

    def _fuzzy_match(self, query: str, start: int, end: int, regex: bool) -> list[int]:
        data = self._data
        if regex:
            import re  # noqa: PLC0415 - only needed on the compatibility path

            pattern = re.compile(query)
            return [i for i in range(start, end) if pattern.search(data.names[i])]
        return [i for i in range(start, end) if query in data.names[i]]

    def _filter_by_parent(
        self, regions: list[Region], parent_level: str, parent_query: str
    ) -> list[Region]:
        """SPEC §2.4: filter by adcode relationship, never by geometry.

        A region's representative point can lie outside its own parent's
        polygon — islands especially — so a geometric test silently drops
        valid matches.
        """
        data = self._data
        if parent_query.isdigit():
            index = data.index_of(parent_query, parent_level)
            if index is None:
                return []
            parent_code = parent_query
        else:
            start, end = data.level_ranges[parent_level]
            candidates = [i for i in data.by_name.get(parent_query, ()) if start <= i < end]
            if not candidates:
                return []
            parent_code = data.adcodes[candidates[0]]

        return [r for r in regions if self._is_under(r, parent_level, parent_code)]

    def _is_under(self, region: Region, parent_level: str, parent_code: str) -> bool:
        if parent_level == "province":
            return region.code[:2] == parent_code[:2]
        if region.level == "district":
            index = self._data.index_of(region.code, "district")
            return index is not None and self._data.parents[index] == parent_code
        return region.code == parent_code

    # ------------------------------------------------------------------
    # Region listing / lookup
    # ------------------------------------------------------------------

    def list_regions(self, level: str) -> list[Region]:
        """List all regions at a given administrative level.

        Parameters
        ----------
        level : str
            ``"province"``, ``"city"``, or ``"district"``.

        Returns
        -------
        list[Region]
            Sorted by adcode ascending.
        """
        if level not in LEVELS:
            raise ValueError(f"Invalid level {level!r}. Must be one of {LEVELS}")
        start, end = self._data.level_ranges[level]
        return [self._region(i) for i in range(start, end)]

    def get_region(self, code: str) -> Region | None:
        """Get a single region by its adcode.

        Parameters
        ----------
        code : str
            e.g. ``"110000"`` for Beijing.

        Returns
        -------
        Region or None
        """
        for level in LEVELS:
            region = self._region_by_code(code, level)
            if region is not None:
                return region
        return None

    # ------------------------------------------------------------------
    # Adcode lookup
    # ------------------------------------------------------------------

    @staticmethod
    def _adcode_level(adcode: str) -> str | None:
        """Detect admin level from a 6-digit adcode, or *None* if invalid."""
        if len(adcode) != 6 or not adcode.isdigit():
            return None
        if adcode.endswith("0000"):
            return "province"
        if adcode.endswith("00"):
            return "city"
        return "district"

    def lookup_adcode(self, adcode: str) -> ReverseResult | None:
        """Look up the administrative hierarchy for a 6-digit adcode.

        Parameters
        ----------
        adcode : str
            6-digit administrative division code (e.g. ``"110108"`` for
            海淀区, ``"440300"`` for 深圳市).

        Returns
        -------
        ReverseResult or None
            The full province/city/district chain, or *None* when the
            adcode is invalid or nothing can be found.
        """
        level = self._adcode_level(adcode)
        if level is None:
            return None

        prefix2 = adcode[:2]
        province_code = prefix2 + "0000"
        province = self._region_by_code(province_code, "province")

        if level == "province":
            return ReverseResult(province=province) if province else None

        if prefix2 in MERGED_PREFIXES:
            city = self._province_as_city(province) if province else None
        elif level == "district":
            index = self._data.index_of(adcode, "district")
            parent = self._data.parents[index] if index is not None else None
            city = self._region_by_code(parent, "city") if parent else None
        else:
            city = self._region_by_code(adcode, "city")

        # Prefecture-level cities with no subdivisions (东莞, 中山, 儋州,
        # 嘉峪关) appear at both levels under one code, so try either way.
        district = self._region_by_code(adcode, "district")

        if province is None and city is None and district is None:
            return None
        return ReverseResult(province=province, city=city, district=district)

    # ------------------------------------------------------------------
    # Containment checks
    # ------------------------------------------------------------------

    def is_in_china(self, lat: float, lng: float) -> bool:
        """Check whether a coordinate falls within China's territory.

        Parameters
        ----------
        lat : float
            Latitude (WGS-84).
        lng : float
            Longitude (WGS-84).

        Returns
        -------
        bool
        """
        return (
            self._data.locate(lat, lng) is not None
            or self._data.locate_province(lat, lng) is not None
        )

    def is_in_region(self, lat: float, lng: float, adcode: str) -> bool:
        """Check whether a coordinate falls within a specific admin region.

        Parameters
        ----------
        lat : float
            Latitude (WGS-84).
        lng : float
            Longitude (WGS-84).
        adcode : str
            6-digit administrative division code (e.g. ``"110108"``).

        Returns
        -------
        bool

        Raises
        ------
        ValueError
            If *adcode* is malformed or does not match any known region.
        """
        level = self._adcode_level(adcode)
        if level is None:
            raise ValueError(f"Invalid adcode: {adcode!r}")
        if self._data.index_of(adcode) is None:
            raise ValueError(f"Region not found for adcode {adcode!r}")

        if level == "province":
            # Answer from the province grid directly: Taiwan has no districts,
            # so routing this through the district lookup would report False
            # for every point on the island.
            province_index = self._data.locate_province(lat, lng)
            return (
                province_index is not None
                and self._data.adcodes[province_index][:2] == adcode[:2]
            )

        index = self._data.locate(lat, lng)
        if index is None:
            return False
        district_code = self._data.adcodes[index]

        if level == "district":
            return district_code == adcode
        # City: municipalities and SARs resolve through the province instead.
        if adcode[:2] in MERGED_PREFIXES:
            return district_code[:2] == adcode[:2]
        return self._data.parents[index] == adcode
