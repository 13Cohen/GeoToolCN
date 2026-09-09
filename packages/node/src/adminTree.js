// Province → city → district tree, built from china_admin.json. SPEC.md §2.10.
//
// Needs no geometry, so it works from the mini dataset too.
import { readFileSync } from "node:fs";
import { dirname, join } from "node:path";
import { fileURLToPath } from "node:url";

import { MERGED_PREFIXES, parentCityCode } from "./hierarchy.js";

const DATA_PATH = join(
  dirname(fileURLToPath(import.meta.url)),
  "..",
  "data",
  "china_admin.json",
);

let cached = null;

function build() {
  const raw = JSON.parse(readFileSync(DATA_PATH, "utf-8"));
  const provinces = new Map(raw.provinces);
  const cityCodes = new Set(raw.cities.map(([code]) => code));

  // Attach each district to the city the hierarchy rules name as its parent.
  // Grouping by 4-digit prefix instead places every province-directly-governed
  // county-level division under all of its siblings, since they share a prefix.
  const districtsByParent = new Map();
  for (const [code, name] of raw.districts) {
    const parent = parentCityCode(code, cityCodes);
    if (parent === null) continue;
    const bucket = districtsByParent.get(parent);
    if (bucket) bucket.push([code, name]);
    else districtsByParent.set(parent, [[code, name]]);
  }

  const citiesByProvince = new Map();
  for (const [code, name] of raw.cities) {
    const prefix2 = code.slice(0, 2);
    const bucket = citiesByProvince.get(prefix2);
    if (bucket) bucket.push([code, name]);
    else citiesByProvince.set(prefix2, [[code, name]]);
  }

  const byCode = ([a], [b]) => (a < b ? -1 : a > b ? 1 : 0);
  const leaf = ([code, name]) => ({ value: code, label: name });

  const tree = [];
  for (const provinceCode of [...provinces.keys()].sort()) {
    const prefix2 = provinceCode.slice(0, 2);
    const label = provinces.get(provinceCode);
    const children = [];

    if (MERGED_PREFIXES.has(prefix2)) {
      // Municipality / SAR: one city node whose value is the province code.
      children.push({
        value: provinceCode,
        label,
        children: (districtsByParent.get(provinceCode) ?? []).sort(byCode).map(leaf),
      });
    } else {
      for (const [cityCode, cityName] of (citiesByProvince.get(prefix2) ?? []).sort(byCode)) {
        children.push({
          value: cityCode,
          label: cityName,
          children: (districtsByParent.get(cityCode) ?? []).sort(byCode).map(leaf),
        });
      }
    }
    tree.push({ value: provinceCode, label, children });
  }
  return tree;
}

/** Province → city → district tree. Cached after the first call. */
export function getAdministrativeTree() {
  if (cached === null) cached = build();
  return cached;
}
