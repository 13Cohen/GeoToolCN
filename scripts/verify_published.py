#!/usr/bin/env python3
"""Check what the registries actually serve, not what the working tree builds.

Every other test in this repository runs against the source tree. That leaves a
whole class of defect invisible, because publishing is not a copy — it rewrites
the version, applies a `files` whitelist, and reaches only what git tracks.

Three real ways this repository can ship something the tree never had:

  - `release.yml` rewrites the version in pyproject.toml from the tag, so a
    literal stored anywhere else goes stale. 3.0.0rc1 passed all twelve checks
    and then reported itself as 2.1.0 once installed.
  - `packages/node/data` is gitignored. It reaches npm only if the publish step
    and the `files` whitelist agree about it — a fresh clone can pass CI while
    the tarball ships a package that cannot load its own dataset.
  - `go get` fetches only what git holds, and go:embed cannot reach outside the
    module. That is the entire reason packages/go/data is committed.

None of those are observable before publishing. So this runs afterwards, and
each ecosystem is installed the way a user installs it.

    python scripts/verify_published.py                       # every ecosystem
    python scripts/verify_published.py --only python
    python scripts/verify_published.py --only python --version 3.0.0rc1

Exits non-zero if any check fails.
"""

from __future__ import annotations

import argparse
import json
import os
import platform
import shutil
import subprocess
import sys
import tempfile
import time
import urllib.request
from dataclasses import dataclass
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
ECOSYSTEMS = ("python", "node", "go", "cli")

# 3.0.0 dropped geopandas and rewrote the hierarchy rules, so the suite only
# describes 3.x. Running it against 2.0.1 would report thousands of failures
# that are not defects.
MIN_CONFORMANCE_VERSION = (3, 0, 0)


@dataclass
class Check:
    name: str
    ok: bool
    detail: str = ""
    skipped: bool = False


def run(cmd, cwd=None, env=None, timeout=900, check=False):
    """Run a command, capturing both streams as text."""
    merged = {**os.environ, **(env or {})}
    return subprocess.run(
        cmd,
        cwd=cwd,
        env=merged,
        capture_output=True,
        text=True,
        timeout=timeout,
        check=check,
    )


def parse_version(text: str) -> tuple[int, ...]:
    """Leading numeric components, so 3.0.0rc1 sorts as (3, 0, 0)."""
    parts: list[int] = []
    for chunk in text.split("."):
        digits = ""
        for ch in chunk:
            if not ch.isdigit():
                break
            digits += ch
        if not digits:
            break
        parts.append(int(digits))
    return tuple(parts)


def conformance(adapter_cmd: str, env=None) -> Check:
    """Run all 35k cases against an adapter that speaks the line protocol."""
    proc = run(
        [sys.executable, str(REPO / "conformance" / "run.py"),
         "--adapter", "cmd", "--cmd", adapter_cmd],
        cwd=REPO,
        env=env,
    )
    tail = (proc.stdout + proc.stderr).strip().splitlines()
    summary = tail[-1] if tail else "no output"
    return Check("conformance suite", proc.returncode == 0, summary)


def outside_repo(path: Path, label: str) -> Check:
    """The point of the whole script: prove we are not testing the source tree.

    Without this every check below could pass while measuring the working copy,
    which is exactly the blind spot this script exists to close.
    """
    resolved = Path(path).resolve()
    inside = REPO == resolved or REPO in resolved.parents
    return Check(
        f"{label} comes from the registry, not this repo",
        not inside,
        str(resolved),
    )


# ---------------------------------------------------------------- Python


def verify_python(version: str | None, work: Path) -> list[Check]:
    checks: list[Check] = []
    venv = work / "venv"
    run([sys.executable, "-m", "venv", str(venv)], check=True)
    py = venv / ("Scripts" if os.name == "nt" else "bin") / "python"

    spec = f"geotool-cn=={version}" if version else "geotool-cn"
    # --pre only when explicitly asking for a prerelease: the default has to
    # mirror what a plain `pip install geotool-cn` gives a user.
    cmd = [str(py), "-m", "pip", "install", "--quiet", spec]
    if version and any(c.isalpha() for c in version.split(".")[-1]):
        cmd.insert(4, "--pre")
    proc = run(cmd)
    if proc.returncode != 0:
        return [Check(f"pip install {spec}", False, proc.stderr.strip()[-400:])]
    checks.append(Check(f"pip install {spec}", True))

    probe = """
import json, os, sys, sysconfig, time
t0 = time.perf_counter()
import GeoToolCN
cold_ms = (time.perf_counter() - t0) * 1000
from importlib.metadata import version
root = os.path.dirname(GeoToolCN.__file__)
size = sum(os.path.getsize(os.path.join(d, n))
           for d, _, ns in os.walk(root) for n in ns)
loaded_geo = "geopandas" in sys.modules or "shapely" in sys.modules
for blocked in ("geopandas", "shapely", "pandas", "numpy"):
    sys.modules[blocked] = None
r = GeoToolCN.reverse(39.9042, 116.4074)
print(json.dumps({
    "root": root,
    "purelib": sysconfig.get_paths()["purelib"],
    "installed": version("geotool-cn"),
    "reported": GeoToolCN.__version__,
    "size_mb": round(size / 1048576, 2),
    "cold_ms": round(cold_ms),
    "pulled_geospatial": loaded_geo,
    "beijing": [r.province.name if r.province else None,
                r.district.name if r.district else None],
    "provinces": len(GeoToolCN.get_administrative_tree()),
}))
"""
    # From the temp dir, so a stray `GeoToolCN/` in the cwd cannot shadow the
    # installed package.
    proc = run([str(py), "-c", probe], cwd=work)
    if proc.returncode != 0:
        checks.append(Check("import and query", False, proc.stderr.strip()[-400:]))
        return checks
    info = json.loads(proc.stdout)

    checks.append(outside_repo(Path(info["root"]), "GeoToolCN"))
    checks.append(Check(
        "installed under site-packages",
        info["root"].startswith(info["purelib"]),
        info["root"],
    ))
    checks.append(Check(
        "__version__ matches the installed version",
        info["reported"] == info["installed"],
        f"reports {info['reported']}, pip installed {info['installed']}",
    ))

    requires = run([str(py), "-m", "pip", "show", "geotool-cn"]).stdout
    line = next((l for l in requires.splitlines() if l.startswith("Requires:")), "")
    deps = line.split(":", 1)[1].strip() if ":" in line else ""
    checks.append(Check("no runtime dependencies", deps == "", deps or "none"))

    checks.append(Check(
        "works without the geospatial stack",
        not info["pulled_geospatial"] and info["beijing"] == ["北京市", "东城区"],
        f"reverse(39.9042,116.4074) -> {info['beijing']}",
    ))
    checks.append(Check(
        "administrative tree intact",
        info["provinces"] == 34,
        f"{info['provinces']} provinces",
    ))
    checks.append(Check(
        "installed size under 8 MB",
        info["size_mb"] < 8,
        f"{info['size_mb']} MB",
    ))
    checks.append(Check(
        "cold start under 100 ms",
        info["cold_ms"] < 100,
        f"{info['cold_ms']} ms",
    ))

    if parse_version(info["installed"]) >= MIN_CONFORMANCE_VERSION:
        checks.append(conformance(
            f'"{py}" "{REPO / "conformance" / "adapters" / "python.py"}"'
        ))
    else:
        checks.append(Check(
            "conformance suite",
            True,
            f"skipped: {info['installed']} predates the suite",
            skipped=True,
        ))
    return checks


# ------------------------------------------------------------------ Node


def verify_node(version: str | None, work: Path) -> list[Check]:
    checks: list[Check] = []
    if not shutil.which("npm"):
        return [Check("npm available", False, "npm not on PATH")]

    proj = work / "node"
    proj.mkdir()
    (proj / "package.json").write_text(
        json.dumps({"name": "verify", "private": True, "type": "module"}) + "\n"
    )

    spec = f"@geotoolcn/core@{version}" if version else "@geotoolcn/core"
    proc = run(["npm", "install", "--no-audit", "--no-fund", spec], cwd=proj)
    if proc.returncode != 0:
        return [Check(f"npm install {spec}", False, proc.stderr.strip()[-400:])]
    checks.append(Check(f"npm install {spec}", True))

    installed = proj / "node_modules" / "@geotoolcn" / "core"
    checks.append(outside_repo(installed, "@geotoolcn/core"))

    manifest = json.loads((installed / "package.json").read_text())
    checks.append(Check(
        "no dependencies",
        not manifest.get("dependencies"),
        json.dumps(manifest.get("dependencies") or {}),
    ))

    # The tarball is built from a gitignored directory, so this is the check
    # that a fresh clone passing CI cannot make.
    gtc = installed / "data" / "china.full.gtc"
    checks.append(Check(
        "the dataset is inside the tarball",
        gtc.exists() and gtc.stat().st_size > 1_000_000,
        f"{gtc.stat().st_size / 1048576:.2f} MB" if gtc.exists() else "data/china.full.gtc missing",
    ))

    types = installed / "index.d.ts"
    checks.append(Check("TypeScript declarations shipped", types.exists()))

    probe = proj / "probe.mjs"
    probe.write_text("""
import { GeoTool, getAdministrativeTree, wgs84ToGcj02 } from "@geotoolcn/core";
const t0 = performance.now();
const geo = new GeoTool();
const cold = performance.now() - t0;
const r = geo.reverse(39.9042, 116.4074);
console.log(JSON.stringify({
  cold_ms: Math.round(cold),
  beijing: [r?.province?.name ?? null, r?.district?.name ?? null],
  provinces: getAdministrativeTree().length,
  converted: wgs84ToGcj02(116.4074, 39.9042),
}));
""")
    proc = run(["node", str(probe)], cwd=proj)
    if proc.returncode != 0:
        checks.append(Check("import and query", False, proc.stderr.strip()[-400:]))
        return checks
    info = json.loads(proc.stdout)
    checks.append(Check(
        "reverse geocoding works",
        info["beijing"] == ["北京市", "东城区"],
        f"reverse(39.9042,116.4074) -> {info['beijing']}",
    ))
    checks.append(Check(
        "administrative tree intact",
        info["provinces"] == 34,
        f"{info['provinces']} provinces",
    ))
    checks.append(Check("cold start under 200 ms", info["cold_ms"] < 200, f"{info['cold_ms']} ms"))

    checks.append(Check(
        "version matches what was requested",
        version is None or manifest["version"] == version,
        f"installed {manifest['version']}",
    ))

    if parse_version(manifest["version"]) >= MIN_CONFORMANCE_VERSION:
        # The adapter is copied next to the installed package so its bare
        # specifier resolves there instead of into the working tree.
        adapter = proj / "adapter.mjs"
        adapter.write_text((REPO / "conformance" / "adapters" / "node.mjs").read_text())
        checks.append(conformance(
            f'node "{adapter}"',
            env={"GEOTOOLCN_MODULE": "@geotoolcn/core"},
        ))
    return checks


# -------------------------------------------------------------------- Go


def verify_go(version: str | None, work: Path) -> list[Check]:
    checks: list[Check] = []
    if not shutil.which("go"):
        return [Check("go available", False, "go not on PATH")]

    module = "github.com/13Cohen/GeoToolCN/packages/go"
    ref = version or "latest"
    gobin = work / "gobin"
    gobin.mkdir()
    env = {
        "GOBIN": str(gobin),
        "GOPATH": str(work / "gopath"),
        "CGO_ENABLED": "0",
        "GOFLAGS": "-mod=mod",
    }

    # Building the adapter straight from the proxy is the strongest form of
    # this check: it fails if the dataset was not committed, because go:embed
    # resolves against what the module server serves, not what a clone builds.
    proc = run(["go", "install", f"{module}/cmd/conformance-adapter@{ref}"],
               cwd=work, env=env)
    if proc.returncode != 0:
        return [Check(f"go install {module}/cmd/conformance-adapter@{ref}", False,
                      proc.stderr.strip()[-600:])]
    checks.append(Check(f"go install ...@{ref}", True))

    adapter = gobin / "conformance-adapter"
    checks.append(outside_repo(adapter, "the compiled adapter"))
    checks.append(Check("adapter binary produced", adapter.exists()))

    # Which version the proxy actually resolved — `latest` is otherwise opaque.
    listing = run(["go", "list", "-m", f"{module}@{ref}"], cwd=work, env=env)
    resolved = listing.stdout.strip().split()[-1] if listing.returncode == 0 else ref
    checks.append(Check("resolved from the module proxy", listing.returncode == 0, resolved))

    # Go needs no publish step, so the module resolves as soon as a commit
    # exists — but until a packages/go/v* tag lands, `go get` hands users a
    # pseudo-version derived from the branch tip. That still works and still
    # deserves the suite; it is just not a release anyone can pin to.
    pseudo = resolved.startswith("v0.0.0-")
    checks.append(Check(
        "resolved to a tagged release",
        not pseudo,
        f"{resolved} — no packages/go/v* tag yet, so `go get` lands on the branch tip"
        if pseudo else resolved,
    ))

    probe = subprocess.run(
        [str(adapter)],
        input='{"op":"reverse","args":[39.9042,116.4074]}\n',
        capture_output=True, text=True, timeout=120,
    )
    checks.append(Check(
        "reverse geocoding works",
        '"110101"' in probe.stdout,
        probe.stdout.strip() or probe.stderr.strip()[-200:],
    ))

    if pseudo or parse_version(resolved.lstrip("v")) >= MIN_CONFORMANCE_VERSION:
        checks.append(conformance(f'"{adapter}"'))
    else:
        checks.append(Check("conformance suite", True,
                            f"skipped: {resolved} predates the suite", skipped=True))
    return checks


# ------------------------------------------------------------------- CLI


def verify_cli(version: str | None, work: Path) -> list[Check]:
    checks: list[Check] = []
    if not shutil.which("gh"):
        return [Check("gh available", False, "gh not on PATH")]

    tag = f"cli-v{version}" if version else None
    if tag is None:
        listing = run(["gh", "release", "list", "--repo", "13Cohen/GeoToolCN",
                       "--limit", "50", "--json", "tagName"])
        if listing.returncode != 0:
            return [Check("list releases", False, listing.stderr.strip()[-300:])]
        tags = [r["tagName"] for r in json.loads(listing.stdout)
                if r["tagName"].startswith("cli-v")]
        if not tags:
            return [Check("a cli-v* release exists", False,
                          "no cli-v* release published yet")]
        tag = sorted(tags)[-1]
    checks.append(Check(f"release {tag} found", True))

    dl = work / "cli"
    dl.mkdir()
    proc = run(["gh", "release", "download", tag, "--repo", "13Cohen/GeoToolCN",
                "--dir", str(dl), "--pattern", "geotoolcn-*"])
    if proc.returncode != 0:
        return checks + [Check(f"download {tag} assets", False, proc.stderr.strip()[-300:])]

    assets = sorted(p.name for p in dl.iterdir())
    expected = {"linux-amd64", "linux-arm64", "darwin-amd64", "darwin-arm64", "windows-amd64.exe"}
    got = {n.replace("geotoolcn-", "") for n in assets}
    checks.append(Check(
        "all five platforms published",
        expected <= got,
        f"{len(got)} assets: {', '.join(sorted(got))}",
    ))

    goos = {"darwin": "darwin", "linux": "linux"}.get(platform.system().lower())
    goarch = {"arm64": "arm64", "aarch64": "arm64",
              "x86_64": "amd64", "amd64": "amd64"}.get(platform.machine().lower())
    native = dl / f"geotoolcn-{goos}-{goarch}"
    if not native.exists():
        checks.append(Check("a binary for this platform", False, f"{goos}/{goarch} not in the release"))
        return checks
    native.chmod(0o755)
    checks.append(outside_repo(native, "the CLI binary"))

    proc = run([str(native), "reverse", "39.9042", "116.4074"], cwd=work)
    ok = proc.returncode == 0 and '"110101"' in proc.stdout
    checks.append(Check("geotoolcn reverse", ok, proc.stdout.strip()[:200] or proc.stderr.strip()[:200]))

    proc = run([str(native), "version"], cwd=work)
    reported = proc.stdout.strip()
    checks.append(Check(
        "version matches the tag",
        tag.removeprefix("cli-v") in reported,
        f"{reported!r} vs tag {tag}",
    ))

    proc = run([str(native), "convert", "wgs84", "gcj02", "116.4074", "39.9042"], cwd=work)
    checks.append(Check("geotoolcn convert", proc.returncode == 0, proc.stdout.strip()[:120]))

    # The HTTP server is the fallback for languages with no binding, so a
    # release that cannot serve is a release that fails those users silently.
    port = 18642
    server = subprocess.Popen(
        [str(native), "serve", "--addr", f"127.0.0.1:{port}"],
        stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True,
    )
    try:
        body = None
        for _ in range(40):
            time.sleep(0.25)
            try:
                with urllib.request.urlopen(
                    f"http://127.0.0.1:{port}/reverse?lat=39.9042&lng=116.4074", timeout=2
                ) as resp:
                    body = resp.read().decode()
                break
            except Exception:  # noqa: BLE001 - still starting up
                continue
        checks.append(Check(
            "geotoolcn serve answers",
            body is not None and "110101" in body,
            (body or "no response").strip()[:200],
        ))
    finally:
        server.terminate()
        server.wait(timeout=10)

    if shutil.which("docker"):
        image = f"ghcr.io/13cohen/geotoolcn:{tag}"
        proc = run(["docker", "run", "--rm", image, "reverse", "39.9042", "116.4074"], timeout=300)
        checks.append(Check(
            "the container image runs",
            proc.returncode == 0 and '"110101"' in proc.stdout,
            proc.stdout.strip()[:200] or proc.stderr.strip()[-200:],
        ))
    else:
        checks.append(Check("the container image runs", True, "skipped: docker not available", skipped=True))
    return checks


# ----------------------------------------------------------------- driver


VERIFIERS = {
    "python": verify_python,
    "node": verify_node,
    "go": verify_go,
    "cli": verify_cli,
}


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__,
                                     formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--only", default="all",
                        help="comma-separated: python,node,go,cli (default: all)")
    parser.add_argument("--version", default=None,
                        help="version to verify; default is whatever the registry serves as latest")
    parser.add_argument("--wait", type=int, default=0, metavar="SECONDS",
                        help="keep retrying while the package is not there yet — registries "
                             "index a publish asynchronously, so a check run straight after "
                             "release.yml sees a 404 that resolves itself in a minute")
    args = parser.parse_args()

    selected = ECOSYSTEMS if args.only == "all" else tuple(
        e.strip() for e in args.only.split(",") if e.strip()
    )
    unknown = [e for e in selected if e not in VERIFIERS]
    if unknown:
        parser.error(f"unknown ecosystem(s): {', '.join(unknown)}")

    print(f"验证已发布产物 — 版本: {args.version or 'registry latest'}")
    print(f"仓库（仅提供测试数据与适配器）: {REPO}\n")

    results: dict[str, list[Check]] = {}
    for eco in selected:
        print(f"── {eco} " + "─" * (60 - len(eco)))
        deadline = time.monotonic() + args.wait
        while True:
            with tempfile.TemporaryDirectory(prefix=f"gtc-verify-{eco}-") as tmp:
                try:
                    checks = VERIFIERS[eco](args.version, Path(tmp))
                except Exception as exc:  # noqa: BLE001 - one ecosystem must not stop the rest
                    checks = [Check("verifier crashed", False, f"{type(exc).__name__}: {exc}")]
            # Only the first check — fetching the artifact — is worth retrying.
            # Anything past it is a real answer about a package that does exist.
            if checks[0].ok or time.monotonic() >= deadline:
                break
            remaining = int(deadline - time.monotonic())
            print(f"  … not indexed yet, retrying for another {remaining}s")
            time.sleep(15)
        results[eco] = checks
        for c in checks:
            mark = "○" if c.skipped else ("✅" if c.ok else "❌")
            print(f"  {mark} {c.name}" + (f"  —  {c.detail}" if c.detail else ""))
        print()

    print("═" * 62)
    failed = 0
    for eco, checks in results.items():
        bad = [c for c in checks if not c.ok]
        skipped = sum(1 for c in checks if c.skipped)
        failed += len(bad)
        status = "通过" if not bad else f"失败 {len(bad)} 项"
        extra = f"（跳过 {skipped}）" if skipped else ""
        print(f"  {eco:<8} {len(checks) - len(bad)}/{len(checks)} {status}{extra}")
    print("═" * 62)
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())
