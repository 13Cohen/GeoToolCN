#!/usr/bin/env bash
#
# Write the version derived from a release tag into an ecosystem's manifest.
#
#   scripts/set_release_version.sh python 3.0.0
#   scripts/set_release_version.sh node   3.0.0
#
# This exists so the logic can be tested before a tag exists. release.yml runs
# only on a real tag push, so until now every line in it was first executed by
# the release it was supposed to perform — `npm version` failed the first npm
# publish outright.
#
# The requirement that is easy to miss: this must be IDEMPOTENT. The version
# committed to the repository is often already the one being released, and
# `npm version 3.0.0` answers "Version not changed" and exits 1 in exactly that
# case. `npm pkg set` does not care what the value was.
set -euo pipefail

ecosystem="${1:?usage: set_release_version.sh <python|node> <version>}"
version="${2:?usage: set_release_version.sh <python|node> <version>}"

case "$ecosystem" in
  python)
    # Not `sed -i`: that flag takes an argument on BSD sed and not on GNU sed,
    # so the same line cannot run on a developer's macOS and on CI.
    tmp="$(mktemp)"
    sed "s/^version = .*/version = \"$version\"/" pyproject.toml > "$tmp"
    mv "$tmp" pyproject.toml
    grep -q "^version = \"$version\"$" pyproject.toml \
      || { echo "failed to set version in pyproject.toml" >&2; exit 1; }
    ;;
  node)
    (cd packages/node && npm pkg set version="$version")
    ;;
  *)
    echo "unknown ecosystem: $ecosystem (expected python or node)" >&2
    exit 1
    ;;
esac

echo "$ecosystem version set to $version"
