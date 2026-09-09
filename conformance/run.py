"""Run the conformance suite against an implementation.

    python conformance/run.py                    # the bundled Python implementation
    python conformance/run.py --adapter cmd --cmd "node adapters/run.mjs"

Any port can be checked by writing an adapter: a process that reads one JSON
request per line on stdin and writes one JSON response per line on stdout.
The protocol is deliberately tiny so that adding a language costs an afternoon
rather than a framework.

    -> {"op":"reverse","args":[39.9,116.4]}
    <- {"ok":["110000","110100","110101"]}
    <- {"error":"invalid adcode"}          # for calls expected to raise

Failures are grouped by tag, because a port is usually wrong about a *category*
of input — boundaries, or municipalities — rather than about scattered points.
"""
from __future__ import annotations

import argparse
import json
import subprocess
import sys
from collections import Counter, defaultdict
from pathlib import Path

SUITE_DIR = Path(__file__).resolve().parent
_ROOT = SUITE_DIR.parent

# Coordinate conversions are float-valued; compare with a tolerance rather than
# for equality, since IEEE-754 evaluation order legitimately differs per language.
# 1e-9 degrees is ~0.1 mm — far below any meaningful positional difference, but
# still roomy next to the ~1 ULP that libm implementations differ by.  A looser
# 1e-6 (~0.1 m) was tried first and let a wrong GCJ-02 semi-major axis through.
COORD_TOLERANCE_DEG = 1e-9
DISTANCE_TOLERANCE_KM = 1e-9

MAX_SHOWN = 8


class PythonAdapter:
    """Calls the bundled implementation in-process."""

    name = "python (in-process)"

    def __init__(self) -> None:
        sys.path.insert(0, str(_ROOT))
        from GeoToolCN import GeoTool  # noqa: PLC0415
        from GeoToolCN import coords  # noqa: PLC0415

        self._geo = GeoTool()
        self._coords = coords

    def call(self, op: str, args):
        geo = self._geo
        try:
            if op == "reverse":
                return self._chain(geo.reverse(*args))
            if op == "lookup_adcode":
                result = geo.lookup_adcode(*args)
                return self._chain(result) if result else None
            if op == "search":
                query, params = args[0], args[1]
                return [r.code for r in geo.search(query, **params)]
            if op == "is_in_china":
                return geo.is_in_china(*args)
            if op == "is_in_region":
                return geo.is_in_region(*args)
            if op == "distance":
                return self._coords.distance(*args)
            return list(getattr(self._coords, op)(*args))
        except Exception as exc:  # noqa: BLE001 - the suite asserts on failures too
            return {"__error__": str(exc)}

    @staticmethod
    def _chain(result):
        return [
            result.province.code if result.province else None,
            result.city.code if result.city else None,
            result.district.code if result.district else None,
        ]


class CommandAdapter:
    """Drives an external implementation over the line protocol."""

    def __init__(self, cmd: str) -> None:
        self.name = cmd
        self._proc = subprocess.Popen(
            cmd,
            shell=True,
            stdin=subprocess.PIPE,
            stdout=subprocess.PIPE,
            text=True,
            encoding="utf-8",
            bufsize=1,
            cwd=str(_ROOT),
        )

    def call(self, op: str, args):
        payload = json.dumps({"op": op, "args": args}, ensure_ascii=False)
        self._proc.stdin.write(payload + "\n")
        self._proc.stdin.flush()
        line = self._proc.stdout.readline()
        if not line:
            raise RuntimeError(f"adapter exited while handling {op}")
        response = json.loads(line)
        if "error" in response:
            return {"__error__": response["error"]}
        return response.get("ok")


def load(name: str) -> list[dict]:
    path = SUITE_DIR / name
    if not path.exists():
        raise SystemExit(
            f"缺少 {path.name}，请先运行 python conformance/generate.py"
        )
    with open(path, encoding="utf-8") as f:
        return [json.loads(line) for line in f if line.strip()]


def close_enough(got, want, tolerance: float) -> bool:
    if isinstance(want, (int, float)) and isinstance(got, (int, float)):
        return abs(got - want) <= tolerance
    if isinstance(want, list) and isinstance(got, list) and len(want) == len(got):
        return all(close_enough(g, w, tolerance) for g, w in zip(got, want))
    return False


class Report:
    def __init__(self) -> None:
        self.passed = 0
        self.failures: list[tuple[str, list[str], object, object]] = []
        self.by_tag: Counter = Counter()
        self.total_by_tag: Counter = Counter()

    def record(self, case: dict, got, want, ok: bool) -> None:
        tags = case.get("tags", [])
        for tag in tags:
            self.total_by_tag[tag] += 1
        if ok:
            self.passed += 1
            return
        for tag in tags:
            self.by_tag[tag] += 1
        self.failures.append((case["id"], tags, got, want))


def run_suite(adapter, report: Report) -> None:
    is_error = lambda v: isinstance(v, dict) and "__error__" in v  # noqa: E731

    for case in load("reverse.jsonl"):
        got = adapter.call("reverse", case["in"])
        report.record(case, got, case["out"], got == case["out"])

    for case in load("lookup.jsonl"):
        got = adapter.call("lookup_adcode", [case["in"]])
        if is_error(got):
            got = None
        report.record(case, got, case["out"], got == case["out"])

    for case in load("search.jsonl"):
        params = {k: v for k, v in case["in"].items() if k != "query"}
        got = adapter.call("search", [case["in"]["query"], params])
        report.record(case, got, case["out"], got == case["out"])

    for case in load("coords.jsonl"):
        got = adapter.call(case["fn"], case["in"])
        tolerance = (
            DISTANCE_TOLERANCE_KM if case["fn"] == "distance" else COORD_TOLERANCE_DEG
        )
        report.record(case, got, case["out"], close_enough(got, case["out"], tolerance))

    for case in load("containment.jsonl"):
        got = adapter.call(case["fn"], case["in"])
        if case["out"] == "error":
            ok = is_error(got)
            got = "error" if ok else got
        else:
            ok = got == case["out"]
        report.record(case, got, case["out"], ok)

    tree_expected = (SUITE_DIR / "tree.sha256").read_text(encoding="utf-8").strip()
    got_tree = adapter.call("tree_sha256", [])
    report.record(
        {"id": "tree-sha256", "tags": ["tree"]},
        got_tree,
        tree_expected,
        got_tree == tree_expected,
    )


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--adapter", choices=["python", "cmd"], default="python")
    parser.add_argument("--cmd", help="adapter command, required with --adapter cmd")
    args = parser.parse_args()

    if args.adapter == "cmd":
        if not args.cmd:
            parser.error("--adapter cmd 需要同时提供 --cmd")
        adapter = CommandAdapter(args.cmd)
    else:
        adapter = PythonAdapter()
        # The in-process adapter answers tree_sha256 itself.
        import hashlib  # noqa: PLC0415

        from GeoToolCN import get_administrative_tree  # noqa: PLC0415

        original = adapter.call

        def call(op, call_args):
            if op == "tree_sha256":
                canonical = json.dumps(
                    get_administrative_tree(),
                    ensure_ascii=False,
                    sort_keys=True,
                    separators=(",", ":"),
                )
                return hashlib.sha256(canonical.encode("utf-8")).hexdigest()
            return original(op, call_args)

        adapter.call = call

    manifest = json.loads((SUITE_DIR / "manifest.json").read_text(encoding="utf-8"))
    print(f"实现:   {adapter.name}")
    print(f"数据集: {manifest['data_version']['fetched_at']}  "
          f"spec v{manifest['spec_version']}\n")

    report = Report()
    run_suite(adapter, report)

    total = report.passed + len(report.failures)
    if not report.failures:
        print(f"通过 {total:,}/{total:,} 条用例。")
        return 0

    print(f"失败 {len(report.failures):,}/{total:,} 条用例\n")
    print("按标签分组：")
    for tag, count in report.by_tag.most_common():
        print(f"  {tag:22s} {count:>6,} / {report.total_by_tag[tag]:,}")
    print(f"\n前 {MAX_SHOWN} 条：")
    for case_id, tags, got, want in report.failures[:MAX_SHOWN]:
        print(f"  {case_id} [{','.join(tags)}]\n    期望 {want}\n    实得 {got}")
    if len(report.failures) > MAX_SHOWN:
        print(f"  ... 另有 {len(report.failures) - MAX_SHOWN:,} 条")
    print(
        "\n每一条差异要么是回归，要么应登记进 "
        "conformance/known-divergences.yaml。"
    )
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
