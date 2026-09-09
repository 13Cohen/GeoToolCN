// Administrative hierarchy rules. SPEC.md §1.4.

export const MERGED_PREFIXES = new Set(["11", "12", "31", "50", "81", "82"]);

/**
 * Resolve a district's parent city adcode.
 *
 * `adcode.slice(0,4) + "00"` looks like the rule and is wrong for the 30
 * province-directly-governed county-level divisions (省直辖县级行政区) in adcode
 * blocks 4190, 4290, 4690 and 6590: it produces codes such as `419000` that name
 * no real division. Those appear in the city layer under their own code.
 *
 * @param {string} districtCode
 * @param {Set<string>} cityCodes
 */
export function parentCityCode(districtCode, cityCodes) {
  const prefix2 = districtCode.slice(0, 2);
  if (MERGED_PREFIXES.has(prefix2)) return `${prefix2}0000`;
  const byPrefix = `${districtCode.slice(0, 4)}00`;
  if (cityCodes.has(byPrefix)) return byPrefix;
  if (cityCodes.has(districtCode)) return districtCode;
  return null;
}
