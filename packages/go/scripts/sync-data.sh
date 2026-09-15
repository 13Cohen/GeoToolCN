#!/usr/bin/env bash
# Copies the built dataset in from the Python package.
#
# Unlike the Node copy, this one IS committed: `go get` fetches only what git
# holds, and go:embed cannot reach outside the module directory, so the Go
# module is the one binding whose dataset has to live in the repository.
# Run this after rebuilding the .gtc and commit the result; CI compares the
# two copies byte for byte and fails when they drift.
set -euo pipefail
here="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
src="$here/../../../GeoToolCN/data"
dst="$here/../data"
for f in china.full.gtc china_admin.json DATA_VERSION.json; do
  if [ ! -f "$src/$f" ]; then
    echo "missing $src/$f — run: python pipeline/build_gtc.py" >&2
    exit 1
  fi
  cp "$src/$f" "$dst/$f"
  echo "synced $f"
done
cp "$here/../../../NOTICE" "$dst/NOTICE"
echo "synced NOTICE"
