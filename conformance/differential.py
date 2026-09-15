"""Differential test: the .gtc implementation against the geopandas reference.

    python conformance/differential.py -n 200000 --boundary 3

The golden suite pins ~39k specific cases; this catches what nobody thought to
pin.  Every difference must match an entry in ``known-divergences.yaml`` —
anything else is a regression.

The geopandas implementation stays in the tree for exactly this reason.  It is
no longer published, but it is the only independent oracle available.  The
golden suite is generated from the .gtc implementation itself, so this run is
what keeps the suite from simply ratifying a regression.

Two samples, because they find different things.  Uniform random points land
in the interior of large districts, where the two implementations agree to the
point of tedium — 300,000 of them produced no district disagreement at all.
Points sampled along every district outline are where quantisation can flip a
point across a boundary (DIV-104), and that class is only credible if the run
measures the distance each such point sits from the disputed boundary and
holds it under the bound the registry claims.  Before it did, any district
disagreement was filed under DIV-104 unread, and inverting the candidate order
in the grid — every overlap band attributed to the other side — passed.
"""
from __future__ import annotations

import argparse
import math
import random
import sys
import time
from collections import Counter
from pathlib import Path

_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(_ROOT))

from GeoToolCN.core import GeoTool as GTCGeoTool  # noqa: E402
from reference.geopandas_impl import GeoTool as ReferenceGeoTool  # noqa: E402

REGISTRY = Path(__file__).resolve().parent / "known-divergences.yaml"
MAX_SHOWN = 10
_METRES_PER_DEGREE = 111_320.0


def chain(result) -> tuple:
    return (
        result.province.code if result and result.province else None,
        result.city.code if result and result.city else None,
        result.district.code if result and result.district else None,
    )


def load_registry() -> dict[str, dict]:
    """id -> entry, from known-divergences.yaml.

    The registry is data, not prose: DIV-104's bound is read from here rather
    than typed into this file a second time.
    """
    import yaml  # noqa: PLC0415 - dev extra, present wherever geopandas is

    with REGISTRY.open(encoding="utf-8") as f:
        doc = yaml.safe_load(f)
    return {entry["id"]: entry for entry in doc["divergences"]}


def boundary_of(geometry):
    """The outline as a line, for distance-to-boundary queries.

    ``make_valid`` turns a self-touching polygon into a GeometryCollection,
    whose ``.boundary`` is None; take the polygon parts' boundaries instead.
    """
    from shapely.ops import unary_union  # noqa: PLC0415

    if geometry is None:
        return None
    if geometry.geom_type == "GeometryCollection":
        parts = [g.boundary for g in geometry.geoms if g.geom_type in ("Polygon", "MultiPolygon")]
        return unary_union(parts) if parts else None
    return geometry.boundary


def boundary_samples(gdf, per_district: int, rng: random.Random):
    """Points jittered off every district outline — the DIV-104 habitat."""
    from conformance.generate import boundary_points  # noqa: PLC0415

    for i in range(len(gdf)):
        for lat, lng in boundary_points(gdf.iloc[i].geometry, per_district, rng):
            yield lat, lng


class Classifier:
    def __init__(self, reference, candidate, registry: dict[str, dict]) -> None:
        gdf = reference._levels["district"].gdf
        self._boundaries = {str(c): boundary_of(g) for c, g in zip(gdf["adcode"], gdf.geometry)}
        step = 10 ** -candidate._data.precision
        bound = registry["DIV-104"]["bound"]
        self._div104_max_degrees = step * float(bound["quantisation_steps"])
        self.div104_max_seen_degrees = 0.0

    def distance_to_disputed_boundary(self, lat: float, lng: float, codes) -> float:
        from shapely.geometry import Point  # noqa: PLC0415

        point = Point(lng, lat)
        distances = [
            self._boundaries[c].distance(point)
            for c in codes
            if c and self._boundaries.get(c) is not None
        ]
        return min(distances) if distances else math.inf

    def classify(self, lat: float, lng: float, reference: tuple, candidate: tuple) -> str | None:
        """Match a difference against the divergence registry.

        Returns the divergence id, or None when the difference is unexplained —
        which is what makes this test worth running.
        """
        ref_province, ref_city, ref_district = reference
        cand_province, cand_city, cand_district = candidate

        if cand_district is None and ref_district is None:
            # DIV-103: the reference could pair a province with another
            # province's city, having tested the city layer independently.
            if (ref_city and ref_province and ref_city[:2] != ref_province[:2]
                    and cand_province == ref_province
                    and (cand_city is None or cand_city[:2] == cand_province[:2])):
                return "DIV-103"
            # DIV-101: with no city geometry in the .gtc there is nothing to
            # derive a city from once the district is missing.
            if ref_city is not None and cand_city is None and cand_province == ref_province:
                return "DIV-101"

        # DIV-104: quantisation to 1e-5 flips attribution near a boundary —
        # and only there. Measured, not assumed.
        if ref_district != cand_district:
            distance = self.distance_to_disputed_boundary(lat, lng, (ref_district, cand_district))
            self.div104_max_seen_degrees = max(self.div104_max_seen_degrees, distance)
            if distance < self._div104_max_degrees:
                return "DIV-104"

        return None


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__,
                                     formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("-n", type=int, default=100_000, help="uniform random points")
    parser.add_argument("--boundary", type=int, default=3, metavar="K",
                        help="points sampled along each district outline (default 3, "
                             "about 8,600 in total; 0 to skip)")
    parser.add_argument("--seed", type=int, default=1)
    args = parser.parse_args()

    print("Loading both implementations...")
    reference = ReferenceGeoTool()
    candidate = GTCGeoTool()
    classifier = Classifier(reference, candidate, load_registry())

    rng = random.Random(args.seed)
    points = [(rng.uniform(3.0, 54.0), rng.uniform(73.0, 136.0)) for _ in range(args.n)]
    n_boundary = 0
    if args.boundary:
        gdf = reference._levels["district"].gdf
        boundary = list(boundary_samples(gdf, args.boundary, rng))
        n_boundary = len(boundary)
        points.extend(boundary)
    total = len(points)
    print(f"Comparing {args.n:,} uniform + {n_boundary:,} boundary points...\n")

    identical = 0
    explained: Counter = Counter()
    unexplained: list[tuple] = []
    started = time.time()

    for i, (lat, lng) in enumerate(points):
        ref = chain(reference.reverse(lat, lng))
        cand = chain(candidate.reverse(lat, lng))
        if ref == cand:
            identical += 1
            continue
        divergence = classifier.classify(lat, lng, ref, cand)
        if divergence:
            explained[divergence] += 1
        else:
            unexplained.append((lat, lng, ref, cand))
        if (i + 1) % 100_000 == 0:
            rate = (i + 1) / (time.time() - started)
            print(f"  {i + 1:>9,} / {total:,}   {rate:,.0f} pts/s")

    print(f"\n一致          {identical:>9,} / {total:,}  ({identical / total * 100:.4f}%)")
    for divergence, count in explained.most_common():
        print(f"已登记 {divergence}  {count:>9,}  ({count / total * 100:.4f}%)")
    if explained["DIV-104"]:
        metres = classifier.div104_max_seen_degrees * _METRES_PER_DEGREE
        print(f"  DIV-104 最远距争议边界 {metres:.3f} m"
              f"（界：{classifier._div104_max_degrees * _METRES_PER_DEGREE:.2f} m）")
    print(f"未登记差异    {len(unexplained):>9,}")

    if unexplained:
        print(f"\n前 {MAX_SHOWN} 条未登记差异：")
        for lat, lng, ref, cand in unexplained[:MAX_SHOWN]:
            extra = ""
            if ref[2] != cand[2]:
                d = classifier.distance_to_disputed_boundary(lat, lng, (ref[2], cand[2]))
                extra = f"  距争议边界 {d * _METRES_PER_DEGREE:.2f} m"
            print(f"  ({lat:.6f}, {lng:.6f}){extra}\n    参考 {ref}\n    GTC  {cand}")
        print(
            "\n每一条要么是回归，要么应登记进 "
            "conformance/known-divergences.yaml。"
        )
        return 1

    print("\n未登记差异为 0。")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
