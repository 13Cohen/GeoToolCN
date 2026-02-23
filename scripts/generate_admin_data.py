#!/usr/bin/env python3
"""Generate china_admin.json from the Tencent LBS administrative division Excel.

Data source
-----------
腾讯位置服务 — 行政区划编码表 Excel
https://lbs.qq.com/service/webService/webServiceGuide/search/webServiceDistrict#9

Usage
-----
1. Download the latest Excel from the URL above and place it in this directory.
2. Run:  python scripts/generate_admin_data.py <path-to-excel>
   Or without argument to auto-detect *.xlsx in this directory.

Output
------
GeoToolCN/data/china_admin.json  (committed to repo, shipped with the package)
"""
from __future__ import annotations

import json
import os
import sys
import glob

_SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
_PROJECT_ROOT = os.path.dirname(_SCRIPT_DIR)
_OUTPUT_PATH = os.path.join(_PROJECT_ROOT, "GeoToolCN", "data", "china_admin.json")

# Prefixes whose city-level entry has the same code as province (XX0000).
# These are special administrative regions where province and city merge.
_HK_MACAU_PREFIXES = {"81", "82"}


def _find_excel() -> str:
    """Auto-detect an .xlsx file in the scripts/ directory."""
    pattern = os.path.join(_SCRIPT_DIR, "*.xlsx")
    files = sorted(glob.glob(pattern))
    if not files:
        sys.exit(
            "Error: No .xlsx file found in scripts/ directory.\n"
            "Download from: https://lbs.qq.com/service/webService/"
            "webServiceGuide/search/webServiceDistrict#9"
        )
    if len(files) > 1:
        print(f"Warning: multiple .xlsx files found, using {files[0]}")
    return files[0]


def main() -> None:
    # Resolve input Excel path
    if len(sys.argv) > 1:
        excel_path = sys.argv[1]
    else:
        excel_path = _find_excel()
    print(f"Reading: {excel_path}")

    try:
        import openpyxl
    except ImportError:
        sys.exit("Error: openpyxl is required. Install with: pip install openpyxl")

    wb = openpyxl.load_workbook(excel_path, read_only=True)
    ws = wb.active

    provinces: list[list[str]] = []
    cities: list[list[str]] = []
    districts: list[list[str]] = []

    for row in ws.iter_rows(values_only=True, min_row=2):
        adcode = str(row[0])
        name_raw = str(row[1])

        # Filter out "境外"
        if adcode == "980000":
            continue

        parts = name_raw.split(",")
        label = parts[-1]
        n_parts = len(parts)

        if n_parts == 2:
            # Province level: "中国,北京市"
            provinces.append([adcode, label])
        elif n_parts == 3:
            # City level: "中国,,北京市" or "中国,江苏省,南京市"
            # HK/Macau only appear here (no province entry in Excel).
            # Add them to provinces as well so the tree has a province node.
            if adcode[:2] in _HK_MACAU_PREFIXES:
                provinces.append([adcode, label])
            cities.append([adcode, label])
        elif n_parts >= 4:
            # District level
            districts.append([adcode, label])

    wb.close()

    # Sort each group by adcode
    provinces.sort(key=lambda x: x[0])
    cities.sort(key=lambda x: x[0])
    districts.sort(key=lambda x: x[0])

    result = {
        "provinces": provinces,
        "cities": cities,
        "districts": districts,
    }

    with open(_OUTPUT_PATH, "w", encoding="utf-8") as f:
        json.dump(result, f, ensure_ascii=False, separators=(",", ":"))

    size = os.path.getsize(_OUTPUT_PATH)
    print(f"\nGenerated: {_OUTPUT_PATH}")
    print(f"  Provinces: {len(provinces)}")
    print(f"  Cities:    {len(cities)}")
    print(f"  Districts: {len(districts)}")
    print(f"  Total:     {len(provinces) + len(cities) + len(districts)}")
    print(f"  File size: {size:,} bytes")


if __name__ == "__main__":
    main()
