#!/usr/bin/env bash
#
# Decide whether a release tag is allowed to publish, and describe it.
#
#   scripts/release_gate.sh py-v3.0.1
#   scripts/release_gate.sh npm-v3.1.0-rc.1 --base origin/master
#   scripts/release_gate.sh packages/go/v3.0.1 --skip-ancestry   # local dry run
#
# Prints `ecosystem=`, `version=` and `prerelease=` lines that release.yml
# appends to $GITHUB_OUTPUT, and exits non-zero when the tag must not ship:
#
#   - the tagged commit is not on the base branch (the tag was cut from a
#     branch CI never approved);
#   - the version in the tag is not the version the repository holds
#     (pyproject.toml for py-v*, packages/node/package.json for npm-v*), so
#     `pip install git+…@tag` would report a different version from PyPI;
#   - a packages/go/vN.x.y tag whose major does not match the /vN suffix in
#     go.mod — the proxy rejects that, and `packages/go/v3.0.0` had to be
#     moved once because nothing checked it beforehand.
#
# The version lives in the repository and the tag must agree with it. That is
# the reverse of rewriting the manifest from the tag at build time, which is
# what release.yml used to do: it meant the same commit could be published
# under two different numbers, and the number in git was never the real one.
# Bump the manifest first (scripts/set_release_version.sh), commit, then tag.
set -euo pipefail

tag="${1:?usage: release_gate.sh <tag> [--base <ref>] [--skip-ancestry]}"
shift
base="origin/master"
check_ancestry=1
while [ $# -gt 0 ]; do
  case "$1" in
    --base) base="$2"; shift 2 ;;
    --skip-ancestry) check_ancestry=0; shift ;;
    *) echo "unknown option: $1" >&2; exit 2 ;;
  esac
done

fail() { echo "::error::$*" >&2; exit 1; }

case "$tag" in
  py-v*)          ecosystem=python; version="${tag#py-v}" ;;
  npm-v*)         ecosystem=node;   version="${tag#npm-v}" ;;
  cli-v*)         ecosystem=cli;    version="${tag#cli-v}" ;;
  # Go keeps the v: it is part of the version the proxy resolves.
  packages/go/v*) ecosystem=go;     version="${tag#packages/go/}" ;;
  *) fail "tag '$tag' matches no release prefix (py-v, npm-v, cli-v, packages/go/v)" ;;
esac
[ -n "$version" ] || fail "tag '$tag' carries no version"

# Anything after the numeric core — rc1, a1, .dev0, -rc.1, -beta — marks a
# pre-release. Each registry spells it differently; the test is the same.
numeric="${version#v}"
if [[ "$numeric" =~ ^[0-9]+(\.[0-9]+)*$ ]]; then
  prerelease=false
else
  prerelease=true
fi

if [ "$check_ancestry" = 1 ]; then
  git merge-base --is-ancestor HEAD "$base" \
    || fail "HEAD ($(git rev-parse --short HEAD)) is not on $base — tag a commit that has been merged"
fi

case "$ecosystem" in
  python)
    held=$(sed -n 's/^version = "\(.*\)"$/\1/p' pyproject.toml | head -1)
    [ "$held" = "$version" ] \
      || fail "tag says $version but pyproject.toml holds $held — bump the manifest and commit before tagging"
    ;;
  node)
    held=$(node -p "require('./packages/node/package.json').version")
    [ "$held" = "$version" ] \
      || fail "tag says $version but packages/node/package.json holds $held — bump the manifest and commit before tagging"
    ;;
  go)
    module=$(head -1 packages/go/go.mod | cut -d' ' -f2)
    major="${version%%.*}"           # v3
    [[ "$major" =~ ^v[0-9]+$ ]] || fail "Go tag version '$version' must start with v<major>"
    if [ "$major" = "v0" ] || [ "$major" = "v1" ]; then
      [[ "$module" =~ /v[0-9]+$ ]] && fail "go.mod path $module carries a major suffix but the tag is $major"
    else
      [[ "$module" == */"$major" ]] \
        || fail "tag major $major but go.mod module path is $module — Go requires the /$major suffix from v2 on"
    fi
    ;;
  cli)
    # Nothing in the tree holds the CLI version: main.go injects it from the
    # tag at build time, and its default is "dev". The image and the binaries
    # are checked for the injected value by verify_published.py.
    ;;
esac

echo "ecosystem=$ecosystem"
echo "version=$version"
echo "prerelease=$prerelease"
