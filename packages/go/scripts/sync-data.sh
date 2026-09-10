#!/usr/bin/env bash
# Copies the built dataset in from the Python package.
#
# The .gtc is not committed per language: 6 MB per binding adds up, and copying
# needs no geopandas, so a fresh clone can still run the Go tests.
set -euo pipefail
here="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
src="$here/../../../GeoToolCN/data"
dst="$here/../data"
for f in china.full.gtc china_admin.json; do
  if [ ! -f "$src/$f" ]; then
    echo "missing $src/$f — run: python pipeline/build_gtc.py" >&2
    exit 1
  fi
  cp "$src/$f" "$dst/$f"
  echo "synced $f"
done
