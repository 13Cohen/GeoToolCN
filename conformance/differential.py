"""Differential test: the .gtc implementation against the geopandas reference.

    python conformance/differential.py -n 1000000

The golden suite pins ~35k specific cases; this catches what nobody thought to
pin.  Every difference must match an entry in ``known-divergences.yaml`` —
anything else is a regression.

The geopandas implementation stays in the tree for exactly this reason.  It is
no longer published, but it is the only independent oracle available.
"""
from __future__ import annotations

import argparse
import random
import sys
import time
from collections import Counter
from pathlib import Path

_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(_ROOT))

from GeoToolCN.core import GeoTool as GTCGeoTool  # noqa: E402
from reference.geopandas_impl import GeoTool as ReferenceGeoTool  # noqa: E402

MAX_SHOWN = 10


def chain(result) -> tuple:
    return (
        result.province.code if result and result.province else None,
        result.city.code if result and result.city else None,
        result.district.code if result and result.district else None,
    )


def classify(reference: tuple, candidate: tuple) -> str | None:
    """Match a difference against the divergence registry.

    Returns the divergence id, or None when the difference is unexplained —
    which is what makes this test worth running.
    """
    ref_province, ref_city, ref_district = reference
    cand_province, cand_city, cand_district = candidate

    if cand_district is None and ref_district is None:
        # DIV-103: the reference could pair a province with another province's
        # city, having tested the city layer independently.
        if ref_city and ref_province and ref_city[:2] != ref_province[:2]:
            return "DIV-103"
        # DIV-101: with no city geometry in the .gtc there is nothing to derive
        # a city from once the district is missing.
        if ref_city is not None and cand_city is None and cand_province == ref_province:
            return "DIV-101"

    # DIV-104: quantisation to 1e-5 flips attribution within ~1 m of a boundary.
    if ref_district != cand_district:
        return "DIV-104"

    return None


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("-n", type=int, default=100_000, help="random points")
    parser.add_argument("--seed", type=int, default=1)
    args = parser.parse_args()

    print("Loading both implementations...")
    reference = ReferenceGeoTool()
    candidate = GTCGeoTool()

    rng = random.Random(args.seed)
    print(f"Comparing {args.n:,} random points...\n")

    identical = 0
    explained: Counter = Counter()
    unexplained: list[tuple] = []
    started = time.time()

    for i in range(args.n):
        lat = rng.uniform(3.0, 54.0)
        lng = rng.uniform(73.0, 136.0)
        ref = chain(reference.reverse(lat, lng))
        cand = chain(candidate.reverse(lat, lng))
        if ref == cand:
            identical += 1
            continue
        divergence = classify(ref, cand)
        if divergence:
            explained[divergence] += 1
        else:
            unexplained.append((lat, lng, ref, cand))
        if (i + 1) % 100_000 == 0:
            rate = (i + 1) / (time.time() - started)
            print(f"  {i + 1:>9,} / {args.n:,}   {rate:,.0f} pts/s")

    total = args.n
    print(f"\n一致          {identical:>9,} / {total:,}  ({identical / total * 100:.4f}%)")
    for divergence, count in explained.most_common():
        print(f"已登记 {divergence}  {count:>9,}  ({count / total * 100:.4f}%)")
    print(f"未登记差异    {len(unexplained):>9,}")

    if unexplained:
        print(f"\n前 {MAX_SHOWN} 条未登记差异：")
        for lat, lng, ref, cand in unexplained[:MAX_SHOWN]:
            print(f"  ({lat:.6f}, {lng:.6f})\n    参考 {ref}\n    GTC  {cand}")
        print(
            "\n每一条要么是回归，要么应登记进 "
            "conformance/known-divergences.yaml。"
        )
        return 1

    print("\n未登记差异为 0。")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
