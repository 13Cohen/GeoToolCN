"""Conformance adapter for the installed geotool-cn package.

    python conformance/run.py --adapter cmd --cmd "python conformance/adapters/python.py"

Reads one JSON request per line on stdin, writes one JSON response per line on
stdout — the same protocol as every other adapter.

`run.py --adapter python` already exercises Python in-process, and is faster.
This file exists because that one inserts the repository root into sys.path, so
it always tests the working tree no matter what is installed. To check what a
registry actually serves, the implementation has to be reached the way a user
reaches it: by importing it, with nothing added to the path.
"""

from __future__ import annotations

import hashlib
import json
import sys

from GeoToolCN import GeoTool, coords
from GeoToolCN.admin_tree import get_administrative_tree

_geo = GeoTool()

_CONVERSIONS = (
    "wgs84_to_gcj02",
    "gcj02_to_wgs84",
    "gcj02_to_bd09",
    "bd09_to_gcj02",
    "wgs84_to_bd09",
    "bd09_to_wgs84",
)


def _chain(result):
    if result is None:
        return None
    return [
        result.province.code if result.province else None,
        result.city.code if result.city else None,
        result.district.code if result.district else None,
    ]


def _handle(op: str, args: list):
    if op == "reverse":
        return _chain(_geo.reverse(*args))
    if op == "lookup_adcode":
        return _chain(_geo.lookup_adcode(*args))
    if op == "search":
        query, params = args[0], args[1]
        return [r.code for r in _geo.search(query, **params)]
    if op == "is_in_china":
        return _geo.is_in_china(*args)
    if op == "is_in_region":
        return _geo.is_in_region(*args)
    if op == "distance":
        return coords.distance(*args)
    if op == "tree_sha256":
        # SPEC §1.3: keys sorted, no whitespace, non-ASCII left unescaped.
        canonical = json.dumps(
            get_administrative_tree(),
            sort_keys=True,
            separators=(",", ":"),
            ensure_ascii=False,
        )
        return hashlib.sha256(canonical.encode("utf-8")).hexdigest()
    if op in _CONVERSIONS:
        return list(getattr(coords, op)(*args))
    raise ValueError(f"unknown op: {op}")


def main() -> None:
    for line in sys.stdin:
        if not line.strip():
            continue
        request = json.loads(line)
        try:
            response = {"ok": _handle(request["op"], request["args"])}
        except Exception as exc:  # noqa: BLE001 - the suite asserts on failures too
            response = {"error": str(exc)}
        sys.stdout.write(json.dumps(response, ensure_ascii=False) + "\n")
        sys.stdout.flush()


if __name__ == "__main__":
    main()
