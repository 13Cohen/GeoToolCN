from __future__ import annotations

import os
from dataclasses import dataclass
from typing import Sequence

import geopandas as gpd
import pandas as pd
from shapely.geometry import Point

from ._hierarchy import MERGED_PREFIXES as _MERGED_PREFIXES
from ._hierarchy import parent_city_code

_LEVELS = ("province", "city", "district")
_FILES = {
    "province": "china_province.geojson",
    "city": "china_city.geojson",
    "district": "china_district.geojson",
}
_DEFAULT_DATA_DIR = os.path.join(os.path.dirname(__file__), "data")


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


@dataclass
class _LevelData:
    """Loaded GeoDataFrame plus prebuilt lookup indexes for one admin level."""

    gdf: gpd.GeoDataFrame
    name_index: dict[str, list[int]]  # name -> row positions
    code_index: dict[str, int]  # adcode -> row position

    @staticmethod
    def load(path: str) -> "_LevelData":
        gdf = gpd.read_file(path)
        # Fix any invalid geometries from the data source
        gdf["geometry"] = gdf["geometry"].make_valid()
        # Ensure spatial index is built
        _ = gdf.sindex

        name_idx: dict[str, list[int]] = {}
        code_idx: dict[str, int] = {}
        for i, row in enumerate(gdf.itertuples()):
            name_idx.setdefault(row.name, []).append(i)
            code_idx[str(row.adcode)] = i
        return _LevelData(gdf=gdf, name_index=name_idx, code_index=code_idx)


class GeoTool:
    """Offline geocoding toolkit for Chinese administrative regions.

    Parameters
    ----------
    data_dir : str, optional
        Directory containing ``china_province.geojson``,
        ``china_city.geojson``, and ``china_district.geojson``.
        Defaults to the bundled data shipped with this package.
    """

    def __init__(self, data_dir: str | None = None) -> None:
        self._data_dir = data_dir or _DEFAULT_DATA_DIR
        self._levels: dict[str, _LevelData] = {}
        self._parent_city: dict[str, str] = {}
        self._load_all()
        self._build_parent_index()

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    def _load_all(self) -> None:
        for level, filename in _FILES.items():
            path = os.path.join(self._data_dir, filename)
            self._levels[level] = _LevelData.load(path)

    def _build_parent_index(self) -> None:
        """Map every district adcode to its parent city adcode.

        Shares :func:`parent_city_code` with ``admin_tree`` so the reverse
        chain and the administrative tree cannot disagree about parentage.
        """
        city_codes = self._levels["city"].code_index
        for code in self._levels["district"].code_index:
            parent = parent_city_code(code, city_codes)
            if parent is not None:
                self._parent_city[code] = parent

    def _hierarchy_from_district(self, district: Region) -> ReverseResult:
        """Build the full province/city/district chain from a resolved district.

        Deriving the upper levels from the district's adcode — rather than
        testing the point against the province and city polygons independently —
        is what keeps the chain self-consistent.  The source layers genuinely
        disagree in places: 加格达奇区 (232718) is administered by 黑龙江省 but
        lies inside 内蒙古自治区's province polygon, and several district
        polygons extend past their own province's outline onto offshore islands.
        An independent per-level lookup reports those as contradictions such as
        ``province=None`` alongside ``city=舟山市``.
        """
        prov_code = district.code[:2] + "0000"
        province = self._lookup_adcode("province", prov_code)

        city_code = self._parent_city.get(district.code)
        if city_code is None:
            city = None
        elif city_code == prov_code:
            # Municipality / SAR: the province doubles as the city.
            city = self._province_as_city(province) if province else None
        else:
            city = self._lookup_adcode("city", city_code)

        return ReverseResult(province=province, city=city, district=district)

    @staticmethod
    def _province_as_city(province: Region) -> Region:
        """Clone a province Region with level set to ``"city"``.

        Used for municipalities and SARs where the province doubles as
        the city to match conventional Chinese geocoding API behaviour.
        """
        return Region(
            name=province.name,
            code=province.code,
            level="city",
            latitude=province.latitude,
            longitude=province.longitude,
        )

    def _point_in_level(self, level: str, point: Point) -> Region | None:
        ld = self._levels[level]
        gdf = ld.gdf
        # Use spatial index for fast candidate filtering
        candidates = list(gdf.sindex.query(point, predicate="intersects"))
        for idx in candidates:
            row = gdf.iloc[idx]
            if row.geometry.contains(point):
                centroid = row.geometry.representative_point()
                return Region(
                    name=row["name"],
                    code=str(row["adcode"]),
                    level=level,
                    latitude=round(centroid.y, 6),
                    longitude=round(centroid.x, 6),
                )
        return None

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
        point = Point(lng, lat)
        district = self._point_in_level("district", point)
        if district is not None:
            return self._hierarchy_from_district(district)

        # No district matched (offshore gaps, disputed strips): fall back to
        # independent per-level lookups.
        province = self._point_in_level("province", point)
        city = self._point_in_level("city", point)
        # Municipalities/SARs have no city-level GeoJSON; use province
        if city is None and province is not None:
            if province.code[:2] in _MERGED_PREFIXES:
                city = self._province_as_city(province)
        return ReverseResult(province=province, city=city, district=None)

    def reverse_batch(
        self, coords: Sequence[tuple[float, float]]
    ) -> list[ReverseResult]:
        """Reverse-geocode many coordinates.

        Delegates to :meth:`reverse` per point.  Earlier versions used
        ``gpd.sjoin``, but the join was measured slower than the per-point
        R-tree path at every batch size tried (1.10x at 50k points, 1.27x at
        1k) — and its per-point result extraction rescanned the whole join
        frame, making 1000 points take 870 ms against 310 ms for a plain loop.

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
            Defaults to *False* (plain substring).  Versions up to 2.0.x
            always matched as a regex, so ``search("东.区")`` matched every
            three-character name ending in 区 and ``search("[")`` raised
            ``re.error``.  Pass ``regex=True`` to restore that behaviour.

        Returns
        -------
        list[Region]

        Examples
        --------
        >>> geo.search("朝阳区", province="北京市")
        [Region(name='朝阳区', ...)]  # only Beijing's 朝阳区
        """
        is_code = query.isdigit()
        levels = [level] if level else list(_LEVELS)
        results: list[Region] = []

        for lvl in levels:
            ld = self._levels[lvl]
            if is_code:
                pos = ld.code_index.get(query)
                if pos is not None:
                    row = ld.gdf.iloc[pos]
                    results.append(self._row_to_region(row, lvl))
            else:
                positions = ld.name_index.get(query)
                if positions:
                    for pos in positions:
                        row = ld.gdf.iloc[pos]
                        results.append(self._row_to_region(row, lvl))
                elif fuzzy:
                    matched = ld.gdf[
                        ld.gdf["name"].str.contains(query, na=False, regex=regex)
                    ]
                    for _, row in matched.iterrows():
                        results.append(self._row_to_region(row, lvl))

        if province is not None:
            results = self._filter_by_parent(results, "province", province)
        if city is not None:
            results = self._filter_by_parent(results, "city", city)

        results.sort(key=lambda r: (_LEVELS.index(r.level), r.code))
        return results

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
            Sorted by adcode ascending.  The source file order is *almost*
            sorted already — 330114 precedes 330113 — so relying on it would
            hand every future port a quirk to reproduce.
        """
        if level not in _LEVELS:
            raise ValueError(
                f"Invalid level {level!r}. Must be one of {_LEVELS}"
            )
        ld = self._levels[level]
        regions = [
            self._row_to_region(ld.gdf.iloc[i], level)
            for i in range(len(ld.gdf))
        ]
        regions.sort(key=lambda r: r.code)
        return regions

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
        for lvl in _LEVELS:
            ld = self._levels[lvl]
            pos = ld.code_index.get(code)
            if pos is not None:
                return self._row_to_region(ld.gdf.iloc[pos], lvl)
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

    def _lookup_adcode(self, level: str, code: str) -> Region | None:
        """Look up a Region by its adcode at a specific level."""
        ld = self._levels[level]
        pos = ld.code_index.get(code)
        if pos is None:
            return None
        return self._row_to_region(ld.gdf.iloc[pos], level)

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
        is_merged = prefix2 in _MERGED_PREFIXES

        # Province
        prov_code = prefix2 + "0000"
        province = self._lookup_adcode("province", prov_code)

        if level == "province":
            return ReverseResult(province=province) if province else None

        # City.  For district-level codes the parent index is authoritative:
        # province-directly-governed county-level divisions such as 济源市
        # (419001) are their own city, which ``adcode[:4] + "00"`` cannot express.
        if is_merged:
            # Municipalities/SARs have no city-level GeoJSON; use province
            city = self._province_as_city(province) if province else None
        elif level == "district":
            city_code = self._parent_city.get(adcode)
            city = self._lookup_adcode("city", city_code) if city_code else None
        else:
            city = self._lookup_adcode("city", adcode[:4] + "00")

        if level == "city":
            # Prefecture-level cities with no subdivisions (东莞市, 中山市,
            # 儋州市, 嘉峪关市) are published at both the city and district
            # level under the same adcode, so reverse() resolves them as a
            # district.  Report the district here too, or the two APIs
            # disagree about the same code.
            district = self._lookup_adcode("district", adcode)
            if province is None and city is None and district is None:
                return None
            return ReverseResult(province=province, city=city, district=district)

        # District
        district = self._lookup_adcode("district", adcode)

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
        return self._point_in_level("province", Point(lng, lat)) is not None

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

        prefix2 = adcode[:2]
        if level == "city" and prefix2 in _MERGED_PREFIXES:
            lookup_code = prefix2 + "0000"
            lookup_level = "province"
        else:
            lookup_code = adcode
            lookup_level = level

        ld = self._levels[lookup_level]
        pos = ld.code_index.get(lookup_code)
        if pos is None:
            raise ValueError(
                f"Region not found for adcode {adcode!r}"
            )

        return ld.gdf.iloc[pos].geometry.contains(Point(lng, lat))

    # ------------------------------------------------------------------
    # Helpers
    # ------------------------------------------------------------------

    def _filter_by_parent(
        self, regions: list[Region], parent_level: str, parent_query: str
    ) -> list[Region]:
        """Keep only regions administratively under *parent_query*.

        Filtering by adcode relationship rather than by geometry: a region's
        representative point can fall outside its own parent's polygon — the
        source layers do not nest perfectly — which silently dropped valid
        matches.  ``search("嵊泗县", province="浙江省")`` used to return nothing
        because 嵊泗县 is an island group lying outside 浙江省's outline.
        """
        parent_ld = self._levels[parent_level]
        if parent_query.isdigit():
            if parent_query not in parent_ld.code_index:
                return []
            parent_code = parent_query
        else:
            positions = parent_ld.name_index.get(parent_query)
            if not positions:
                return []
            parent_code = str(parent_ld.gdf.iloc[positions[0]]["adcode"])

        return [r for r in regions if self._is_under(r, parent_level, parent_code)]

    def _is_under(self, region: Region, parent_level: str, parent_code: str) -> bool:
        """Whether *region* sits at or below *parent_code* in the hierarchy."""
        if parent_level == "province":
            return region.code[:2] == parent_code[:2]
        # parent_level == "city"
        if region.level == "district":
            return self._parent_city.get(region.code) == parent_code
        return region.code == parent_code

    @staticmethod
    def _row_to_region(row: pd.Series, level: str) -> Region:
        pt = row.geometry.representative_point()
        return Region(
            name=row["name"],
            code=str(row["adcode"]),
            level=level,
            latitude=round(pt.y, 6),
            longitude=round(pt.x, 6),
        )
