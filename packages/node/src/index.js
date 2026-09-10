// Offline geocoding for Chinese administrative regions. No dependencies.
//
// The contract is SPEC.md §2; this implementation is checked against the same
// ~35k conformance cases as the Python one.

import { readFileSync } from "node:fs";
import { dirname, join } from "node:path";
import { fileURLToPath } from "node:url";

import { GTCData, LEVELS } from "./gtc.js";
import { MERGED_PREFIXES } from "./hierarchy.js";

export { getAdministrativeTree } from "./adminTree.js";
export {
  bd09ToGcj02,
  bd09ToWgs84,
  distance,
  gcj02ToBd09,
  gcj02ToWgs84,
  wgs84ToBd09,
  wgs84ToGcj02,
} from "./coords.js";
export { GTCFormatError, GeometryUnavailable } from "./gtc.js";

const DEFAULT_DATA = join(
  dirname(fileURLToPath(import.meta.url)),
  "..",
  "data",
  "china.full.gtc",
);

export class GeoTool {
  /** @param {string} [dataPath] Path to a .gtc file. Defaults to the bundled one. */
  constructor(dataPath = DEFAULT_DATA) {
    this.data = new GTCData(readFileSync(dataPath));
  }

  #region(index) {
    const data = this.data;
    return {
      name: data.names[index],
      code: data.adcodes[index],
      level: LEVELS[data.levels[index]],
      latitude: data.lats[index],
      longitude: data.lngs[index],
    };
  }

  #regionByCode(code, level) {
    const index = this.data.indexOf(code, level);
    return index === null ? null : this.#region(index);
  }

  /** Municipalities and SARs report the province as their city. */
  static #provinceAsCity(province) {
    return { ...province, level: "city" };
  }

  /**
   * SPEC §2.1: derive the upper levels from the district's adcode.
   *
   * Testing each layer independently produces contradictions, because the
   * source layers overlap and disagree with each other.
   */
  #chainFromDistrict(index) {
    const district = this.#region(index);
    const provinceCode = `${district.code.slice(0, 2)}0000`;
    const province = this.#regionByCode(provinceCode, "province");

    const parent = this.data.parents[index];
    let city = null;
    if (parent === provinceCode) {
      city = province ? GeoTool.#provinceAsCity(province) : null;
    } else if (parent !== null) {
      city = this.#regionByCode(parent, "city");
    }
    return { province, city, district };
  }

  /** Look up the administrative region for a WGS-84 coordinate. */
  reverse(lat, lng) {
    const index = this.data.locate(lat, lng);
    if (index !== null) return this.#chainFromDistrict(index);

    // No district covers the point — Taiwan is published at province level
    // only, and coastal gaps leave slivers between districts. The city stays
    // null because the .gtc carries no city geometry.
    const provinceIndex = this.data.locateProvince(lat, lng);
    if (provinceIndex === null) return { province: null, city: null, district: null };
    const province = this.#region(provinceIndex);
    const city = MERGED_PREFIXES.has(province.code.slice(0, 2))
      ? GeoTool.#provinceAsCity(province)
      : null;
    return { province, city, district: null };
  }

  /** @param {Array<[number, number]>} coords */
  reverseBatch(coords) {
    return coords.map(([lat, lng]) => this.reverse(lat, lng));
  }

  /**
   * Search by name or adcode.
   * @param {string} query
   * @param {{level?: string, province?: string, city?: string, fuzzy?: boolean}} [options]
   */
  search(query, options = {}) {
    const { level = null, province = null, city = null, fuzzy = true } = options;
    const data = this.data;
    const levels = level ? [level] : LEVELS;
    const matches = [];

    for (const levelName of levels) {
      const [start, end] = data.levelRanges[levelName];
      if (/^\d+$/.test(query)) {
        for (let i = start; i < end; i += 1) {
          if (data.adcodes[i] === query) matches.push(i);
        }
        continue;
      }
      const exact = (data.byName.get(query) ?? []).filter((i) => i >= start && i < end);
      if (exact.length) {
        matches.push(...exact);
      } else if (fuzzy) {
        // Literal substring, never a regex: dialects differ across languages,
        // so a regex could not mean the same thing in every port.
        for (let i = start; i < end; i += 1) {
          if (data.names[i].includes(query)) matches.push(i);
        }
      }
    }

    let regions = matches.map((i) => this.#region(i));
    if (province !== null) regions = this.#filterByParent(regions, "province", province);
    if (city !== null) regions = this.#filterByParent(regions, "city", city);

    regions.sort((a, b) => {
      const byLevel = LEVELS.indexOf(a.level) - LEVELS.indexOf(b.level);
      return byLevel !== 0 ? byLevel : a.code < b.code ? -1 : a.code > b.code ? 1 : 0;
    });
    return regions;
  }

  /**
   * SPEC §2.4: filter by adcode relationship, never by geometry.
   *
   * A region's representative point can lie outside its own parent's polygon —
   * islands especially — so a geometric test silently drops valid matches.
   */
  #filterByParent(regions, parentLevel, parentQuery) {
    const data = this.data;
    let parentCode;
    if (/^\d+$/.test(parentQuery)) {
      if (data.indexOf(parentQuery, parentLevel) === null) return [];
      parentCode = parentQuery;
    } else {
      const [start, end] = data.levelRanges[parentLevel];
      const candidates = (data.byName.get(parentQuery) ?? []).filter(
        (i) => i >= start && i < end,
      );
      if (!candidates.length) return [];
      parentCode = data.adcodes[candidates[0]];
    }
    return regions.filter((r) => this.#isUnder(r, parentLevel, parentCode));
  }

  #isUnder(region, parentLevel, parentCode) {
    if (parentLevel === "province") {
      return region.code.slice(0, 2) === parentCode.slice(0, 2);
    }
    if (region.level === "district") {
      const index = this.data.indexOf(region.code, "district");
      return index !== null && this.data.parents[index] === parentCode;
    }
    return region.code === parentCode;
  }

  /** All regions at a level, sorted by adcode. */
  listRegions(level) {
    if (!LEVELS.includes(level)) {
      throw new TypeError(`Invalid level ${JSON.stringify(level)}. Must be one of ${LEVELS}`);
    }
    const [start, end] = this.data.levelRanges[level];
    const out = [];
    for (let i = start; i < end; i += 1) out.push(this.#region(i));
    return out;
  }

  /** A single region by adcode, searching province → city → district. */
  getRegion(code) {
    for (const level of LEVELS) {
      const region = this.#regionByCode(code, level);
      if (region !== null) return region;
    }
    return null;
  }

  static #adcodeLevel(adcode) {
    if (adcode.length !== 6 || !/^\d{6}$/.test(adcode)) return null;
    if (adcode.endsWith("0000")) return "province";
    if (adcode.endsWith("00")) return "city";
    return "district";
  }

  /** The full province/city/district chain for a 6-digit adcode. */
  lookupAdcode(adcode) {
    const level = GeoTool.#adcodeLevel(adcode);
    if (level === null) return null;

    const prefix2 = adcode.slice(0, 2);
    const province = this.#regionByCode(`${prefix2}0000`, "province");
    if (level === "province") {
      return province ? { province, city: null, district: null } : null;
    }

    let city = null;
    if (MERGED_PREFIXES.has(prefix2)) {
      city = province ? GeoTool.#provinceAsCity(province) : null;
    } else if (level === "district") {
      const index = this.data.indexOf(adcode, "district");
      const parent = index === null ? null : this.data.parents[index];
      city = parent ? this.#regionByCode(parent, "city") : null;
    } else {
      city = this.#regionByCode(adcode, "city");
    }

    // Prefecture-level cities with no subdivisions (东莞, 中山, 儋州, 嘉峪关)
    // appear at both levels under one code, so try either way.
    const district = this.#regionByCode(adcode, "district");

    if (province === null && city === null && district === null) return null;
    return { province, city, district };
  }

  isInChina(lat, lng) {
    return (
      this.data.locate(lat, lng) !== null ||
      this.data.locateProvince(lat, lng) !== null
    );
  }

  /** @throws {TypeError} if the adcode is malformed or unknown. */
  isInRegion(lat, lng, adcode) {
    const level = GeoTool.#adcodeLevel(adcode);
    if (level === null) throw new TypeError(`Invalid adcode: ${JSON.stringify(adcode)}`);
    if (this.data.indexOf(adcode) === null) {
      throw new TypeError(`Region not found for adcode ${JSON.stringify(adcode)}`);
    }

    if (level === "province") {
      // Answer from the province grid: Taiwan has no districts, so routing
      // this through the district lookup reports false for the whole island.
      const provinceIndex = this.data.locateProvince(lat, lng);
      return (
        provinceIndex !== null &&
        this.data.adcodes[provinceIndex].slice(0, 2) === adcode.slice(0, 2)
      );
    }

    const index = this.data.locate(lat, lng);
    if (index === null) return false;
    const districtCode = this.data.adcodes[index];
    if (level === "district") return districtCode === adcode;
    if (MERGED_PREFIXES.has(adcode.slice(0, 2))) {
      return districtCode.slice(0, 2) === adcode.slice(0, 2);
    }
    return this.data.parents[index] === adcode;
  }
}

// ---------------------------------------------------------------------------
// Module-level shortcuts sharing one lazily-created instance.
// ---------------------------------------------------------------------------

let shared = null;
const instance = () => (shared ??= new GeoTool());

export const reverse = (lat, lng) => instance().reverse(lat, lng);
export const reverseBatch = (coords) => instance().reverseBatch(coords);
export const search = (query, options) => instance().search(query, options);
export const listRegions = (level) => instance().listRegions(level);
export const getRegion = (code) => instance().getRegion(code);
export const lookupAdcode = (adcode) => instance().lookupAdcode(adcode);
export const isInChina = (lat, lng) => instance().isInChina(lat, lng);
export const isInRegion = (lat, lng, adcode) => instance().isInRegion(lat, lng, adcode);
