# Data Update Report

**Date**: 2026-03-07
**Source**: [DataV.GeoAtlas (阿里云 DataV 地理小工具)](https://datav.aliyun.com/tools/atlas)
**CRS**: GCJ-02 → WGS-84

## Initial Import (switched from 天地图 + 腾讯 LBS to unified DataV source)

| Level | Count |
|-------|-------|
| Provinces | 34 |
| Cities | 363 |
| Districts | 2874 |

### Key Changes from Previous Data Sources

- **Unified data source**: Both GeoJSON boundaries and admin tree now come from the same DataV/Amap source
- **Code format**: Changed from 9-digit GB codes (e.g. `156110000`) to 6-digit adcodes (e.g. `110000`)
- **Coordinate system**: GCJ-02 converted to WGS-84
- **Taiwan**: Province-level boundary only (DataV does not provide sub-level data)
- **Macau**: Now has 8 districts (previously 3 in Tencent data)
- **No boundary lines**: Removed non-administrative features (九段线 etc.) that were in 天地图
