from __future__ import annotations

import os
from dataclasses import dataclass, field
from typing import Sequence

import geopandas as gpd
import pandas as pd
from shapely.geometry import Point

_LEVELS = ("province", "city", "district")
_FILES = {
    "province": "china_province.geojson",
    "city": "china_city.geojson",
    "district": "china_district.geojson",
}
_DEFAULT_DATA_DIR = os.path.join(os.path.dirname(__file__), "data")

# Municipalities (直辖市) and SARs (特别行政区) whose city-level GB code
# in the GeoJSON data equals the province-level GB code.
_MERGED_PREFIXES = frozenset({"11", "12", "31", "50", "81", "82"})


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
    code_index: dict[str, int]  # gb code -> row position

    @staticmethod
    def load(path: str) -> "_LevelData":
        gdf = gpd.read_file(path)
        # Ensure spatial index is built
        _ = gdf.sindex

        name_idx: dict[str, list[int]] = {}
        code_idx: dict[str, int] = {}
        for i, row in enumerate(gdf.itertuples()):
            name_idx.setdefault(row.name, []).append(i)
            code_idx[row.gb] = i
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
        self._load_all()

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    def _load_all(self) -> None:
        for level, filename in _FILES.items():
            path = os.path.join(self._data_dir, filename)
            self._levels[level] = _LevelData.load(path)

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
                    code=row["gb"],
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
        return ReverseResult(
            province=self._point_in_level("province", point),
            city=self._point_in_level("city", point),
            district=self._point_in_level("district", point),
        )

    def reverse_batch(
        self, coords: Sequence[tuple[float, float]]
    ) -> list[ReverseResult]:
        """Reverse-geocode many coordinates at once using spatial join.

        Parameters
        ----------
        coords : sequence of (lat, lng) tuples

        Returns
        -------
        list[ReverseResult]
        """
        if not coords:
            return []

        points = [Point(lng, lat) for lat, lng in coords]
        pts_gdf = gpd.GeoDataFrame(
            {"idx": range(len(coords))},
            geometry=points,
            crs=self._levels["province"].gdf.crs,
        )

        joined: dict[str, pd.DataFrame] = {}
        for level in _LEVELS:
            gdf = self._levels[level].gdf
            j = gpd.sjoin(pts_gdf, gdf, how="left", predicate="within")
            joined[level] = j

        results: list[ReverseResult] = []
        for i, pt in enumerate(points):
            kw: dict[str, Region | None] = {}
            for level in _LEVELS:
                j = joined[level]
                rows = j[j["idx"] == i]
                if rows.empty or pd.isna(rows.iloc[0].get("index_right")):
                    kw[level] = None
                else:
                    row = rows.iloc[0]
                    level_gdf = self._levels[level].gdf
                    matched_geom = level_gdf.iloc[int(row["index_right"])].geometry
                    rep = matched_geom.representative_point()
                    kw[level] = Region(
                        name=row["name"],
                        code=row["gb"],
                        level=level,
                        latitude=round(rep.y, 6),
                        longitude=round(rep.x, 6),
                    )
            results.append(ReverseResult(**kw))
        return results

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
    ) -> list[Region]:
        """Search for regions by name or GB admin code.

        Parameters
        ----------
        query : str
            Region name (e.g. ``"深圳市"``) or GB code (e.g. ``"156440300"``).
        level : str, optional
            Restrict to ``"province"``, ``"city"``, or ``"district"``.
        province : str, optional
            Filter results to those within this province (name or GB code).
        city : str, optional
            Filter results to those within this city (name or GB code).
        fuzzy : bool
            If *True* (default), also match regions whose name *contains*
            the query when no exact match is found.

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
                    matched = ld.gdf[ld.gdf["name"].str.contains(query, na=False)]
                    for _, row in matched.iterrows():
                        results.append(self._row_to_region(row, lvl))

        if province is not None:
            results = self._filter_by_parent(results, "province", province)
        if city is not None:
            results = self._filter_by_parent(results, "city", city)

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
        """
        if level not in _LEVELS:
            raise ValueError(
                f"Invalid level {level!r}. Must be one of {_LEVELS}"
            )
        ld = self._levels[level]
        return [
            self._row_to_region(ld.gdf.iloc[i], level)
            for i in range(len(ld.gdf))
        ]

    def get_region(self, code: str) -> Region | None:
        """Get a single region by its GB admin code.

        Parameters
        ----------
        code : str
            e.g. ``"156110000"`` for Beijing.

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
    def _adcode_to_gb(adcode: str) -> str:
        """Convert a 6-digit adcode to a 9-digit GB code."""
        return "156" + adcode

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

    def _lookup_gb(self, level: str, gb_code: str) -> Region | None:
        """Look up a Region by its 9-digit GB code at a specific level."""
        ld = self._levels[level]
        pos = ld.code_index.get(gb_code)
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
        prov_gb = self._adcode_to_gb(prefix2 + "0000")
        province = self._lookup_gb("province", prov_gb)

        if level == "province":
            return ReverseResult(province=province) if province else None

        # City
        if is_merged:
            city = self._lookup_gb("city", prov_gb)
        else:
            city = self._lookup_gb("city", self._adcode_to_gb(adcode[:4] + "00"))

        if level == "city":
            if province is None and city is None:
                return None
            return ReverseResult(province=province, city=city)

        # District
        district = self._lookup_gb("district", self._adcode_to_gb(adcode))

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
            gb_code = self._adcode_to_gb(prefix2 + "0000")
        else:
            gb_code = self._adcode_to_gb(adcode)

        ld = self._levels[level]
        pos = ld.code_index.get(gb_code)
        if pos is None:
            raise ValueError(
                f"Region not found for adcode {adcode!r} (GB code {gb_code!r})"
            )

        return ld.gdf.iloc[pos].geometry.contains(Point(lng, lat))

    # ------------------------------------------------------------------
    # Helpers
    # ------------------------------------------------------------------

    def _filter_by_parent(
        self, regions: list[Region], parent_level: str, parent_query: str
    ) -> list[Region]:
        """Keep only regions whose representative point is within *parent_query*."""
        # Resolve parent geometry
        parent_ld = self._levels[parent_level]
        if parent_query.isdigit():
            pos = parent_ld.code_index.get(parent_query)
            if pos is None:
                return []
            parent_geom = parent_ld.gdf.iloc[pos].geometry
        else:
            positions = parent_ld.name_index.get(parent_query)
            if not positions:
                return []
            parent_geom = parent_ld.gdf.iloc[positions[0]].geometry

        filtered: list[Region] = []
        for r in regions:
            if r.latitude is not None and r.longitude is not None:
                pt = Point(r.longitude, r.latitude)
                if parent_geom.contains(pt):
                    filtered.append(r)
        return filtered

    @staticmethod
    def _row_to_region(row: pd.Series, level: str) -> Region:
        pt = row.geometry.representative_point()
        return Region(
            name=row["name"],
            code=row["gb"],
            level=level,
            latitude=round(pt.y, 6),
            longitude=round(pt.x, 6),
        )
