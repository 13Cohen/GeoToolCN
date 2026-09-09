// Reader for the .gtc binary. No dependencies.
//
// Format: SPEC.md §4. Behaviour: SPEC.md §2 and §3.
//
// A lookup is a binary search in a run-length table; only when that misses does
// any geometry get decoded — roughly 23% of queries, against an average of two
// candidate polygons. That is the whole reason this file is short enough to be
// worth porting rather than binding to a native library.

export const LEVELS = ["province", "city", "district"];

const MAGIC = 0x4e435447; // "GTCN" read as little-endian u32
const SUPPORTED_FORMAT_VERSION = 1;

const SECTION_META = 1;
const SECTION_NAMES = 2;
const SECTION_GEOM = 3;
const SECTION_GEOM_INDEX = 4;
const SECTION_GRID_SOLID = 5;
const SECTION_GRID_MIXED_CELLS = 6;
const SECTION_GRID_MIXED_PTRS = 7;
const SECTION_GRID_MIXED_LISTS = 8;
const SECTION_GRID_PROV_SOLID = 9;
const SECTION_GRID_PROV_MIXED_CELLS = 10;
const SECTION_GRID_PROV_MIXED_PTRS = 11;
const SECTION_GRID_PROV_MIXED_LISTS = 12;

const META_RECORD_SIZE = 28;

export class GTCFormatError extends Error {}
export class GeometryUnavailable extends Error {}

/**
 * Largest index i where table[i] <= value, or -1.
 * @param {Uint32Array} table
 * @param {number} value
 */
function upperBound(table, value) {
  let low = 0;
  let high = table.length;
  while (low < high) {
    const mid = (low + high) >>> 1;
    if (table[mid] <= value) low = mid + 1;
    else high = mid;
  }
  return low - 1;
}

/**
 * Index of value in a sorted table, or -1.
 * @param {Uint32Array} table
 * @param {number} value
 */
function exactSearch(table, value) {
  let low = 0;
  let high = table.length - 1;
  while (low <= high) {
    const mid = (low + high) >>> 1;
    if (table[mid] === value) return mid;
    if (table[mid] < value) low = mid + 1;
    else high = mid - 1;
  }
  return -1;
}

export class GTCData {
  /** @param {Uint8Array} bytes */
  constructor(bytes) {
    this.bytes = bytes;
    const view = new DataView(bytes.buffer, bytes.byteOffset, bytes.byteLength);
    this.view = view;

    if (view.getUint32(0, true) !== MAGIC) {
      throw new GTCFormatError("not a .gtc file");
    }
    const formatVersion = view.getUint16(4, true);
    if (formatVersion !== SUPPORTED_FORMAT_VERSION) {
      throw new GTCFormatError(
        `format version ${formatVersion} is not supported ` +
          `(this build reads version ${SUPPORTED_FORMAT_VERSION})`,
      );
    }

    this.dataset = view.getUint8(6);
    this.precision = view.getUint8(7);
    this.dataVersion = view.getUint32(8, true);
    const sectionCount = view.getUint16(12, true);
    this.originLng = view.getInt32(16, true) / 1e6;
    this.originLat = view.getInt32(20, true) / 1e6;
    this.gridStep = view.getUint32(24, true) / 1e6;
    this.gridWidth = view.getUint16(28, true);
    this.gridHeight = view.getUint16(30, true);
    this.scale = 10 ** this.precision;

    /** @type {Map<number, {offset: number, length: number}>} */
    const sections = new Map();
    for (let i = 0; i < sectionCount; i += 1) {
      const base = 32 + 24 * i;
      sections.set(view.getUint16(base, true), {
        offset: Number(view.getBigUint64(base + 8, true)),
        length: Number(view.getBigUint64(base + 16, true)),
      });
    }
    this.sections = sections;

    const meta = sections.get(SECTION_META);
    this.metaOffset = meta.offset;
    this.recordCount = view.getUint32(meta.offset, true);

    const names = sections.get(SECTION_NAMES);
    this.namesOffset = names.offset;

    const geom = sections.get(SECTION_GEOM);
    this.geomOffset = geom.offset;
    this.hasGeometry = geom.length > 0;
    this.geomIndex = this.#u32(SECTION_GEOM_INDEX);

    this.districtGrid = this.#loadGrid(
      SECTION_GRID_SOLID,
      SECTION_GRID_MIXED_CELLS,
      SECTION_GRID_MIXED_PTRS,
      SECTION_GRID_MIXED_LISTS,
    );
    this.provinceGrid = this.#loadGrid(
      SECTION_GRID_PROV_SOLID,
      SECTION_GRID_PROV_MIXED_CELLS,
      SECTION_GRID_PROV_MIXED_PTRS,
      SECTION_GRID_PROV_MIXED_LISTS,
    );

    /** @type {Map<number, {bbox: Int32Array, polygons: Array}>} */
    this.geometryCache = new Map();
    this.#buildIndexes();
  }

  /**
   * Copy a section out as a Uint32Array.
   *
   * `slice` rather than a view: the file's own offset need not be 4-byte
   * aligned within the underlying ArrayBuffer, and a misaligned typed array
   * throws.
   */
  #u32(sectionType, byteOffset = 0, byteLength = null) {
    const section = this.sections.get(sectionType);
    const start = this.bytes.byteOffset + section.offset + byteOffset;
    const length = byteLength ?? section.length - byteOffset;
    return new Uint32Array(this.bytes.buffer.slice(start, start + length));
  }

  #loadGrid(solidType, cellsType, ptrsType, listsType) {
    const solidSection = this.sections.get(solidType);
    const runCount = this.view.getUint32(solidSection.offset, true);
    const flat = this.#u32(solidType, 4, 12 * runCount);

    const runStart = new Uint32Array(runCount);
    const runLength = new Uint32Array(runCount);
    const runValue = new Uint32Array(runCount);
    for (let i = 0; i < runCount; i += 1) {
      runStart[i] = flat[i * 3];
      runLength[i] = flat[i * 3 + 1];
      runValue[i] = flat[i * 3 + 2];
    }

    const cellsSection = this.sections.get(cellsType);
    const mixedCount = this.view.getUint32(cellsSection.offset, true);
    return {
      runStart,
      runLength,
      runValue,
      mixedCells: this.#u32(cellsType, 4, 4 * mixedCount),
      mixedPtrs: this.#u32(ptrsType),
      mixedLists: this.#u32(listsType),
    };
  }

  #buildIndexes() {
    const { view, recordCount } = this;
    const decoder = new TextDecoder("utf-8");

    this.adcodes = new Array(recordCount);
    this.levels = new Uint8Array(recordCount);
    this.parents = new Array(recordCount);
    this.names = new Array(recordCount);
    this.lats = new Float64Array(recordCount);
    this.lngs = new Float64Array(recordCount);
    this.byCode = new Map();
    this.byName = new Map();
    this.levelRanges = {};

    let offset = this.metaOffset + 4;
    for (let i = 0; i < recordCount; i += 1) {
      const adcode = view.getUint32(offset, true);
      const level = view.getUint8(offset + 4);
      const parent = view.getUint32(offset + 8, true);
      const nameOffset = view.getUint32(offset + 12, true);
      const nameLength = view.getUint16(offset + 16, true);
      const lat = view.getInt32(offset + 20, true);
      const lng = view.getInt32(offset + 24, true);
      offset += META_RECORD_SIZE;

      const code = String(adcode).padStart(6, "0");
      this.adcodes[i] = code;
      this.levels[i] = level;
      this.parents[i] = parent ? String(parent).padStart(6, "0") : null;
      const nameStart = this.bytes.byteOffset + this.namesOffset + nameOffset;
      const name = decoder.decode(
        new Uint8Array(this.bytes.buffer, nameStart, nameLength),
      );
      this.names[i] = name;
      this.lats[i] = lat / 1e6;
      this.lngs[i] = lng / 1e6;

      if (!this.byCode.has(code)) this.byCode.set(code, i);
      const sameName = this.byName.get(name);
      if (sameName) sameName.push(i);
      else this.byName.set(name, [i]);
    }

    // Records are sorted by (level, adcode), so each level is contiguous.
    for (let levelId = 0; levelId < LEVELS.length; levelId += 1) {
      let start = -1;
      let end = -1;
      for (let i = 0; i < recordCount; i += 1) {
        if (this.levels[i] === levelId) {
          if (start === -1) start = i;
          end = i + 1;
        }
      }
      this.levelRanges[LEVELS[levelId]] = start === -1 ? [0, 0] : [start, end];
    }
  }

  /**
   * @param {string} code
   * @param {string|null} level
   */
  indexOf(code, level = null) {
    const index = this.byCode.get(code);
    if (index === undefined) return null;
    if (level !== null && this.levels[index] !== LEVELS.indexOf(level)) {
      // A code can exist at two levels (东莞市 is both city and district).
      const [start, end] = this.levelRanges[level];
      for (let i = start; i < end; i += 1) {
        if (this.adcodes[i] === code) return i;
      }
      return null;
    }
    return index;
  }

  /**
   * Decode one region's polygons, caching the result.
   *
   * Deferred because most lookups never need it: a solid grid cell answers
   * outright, and eagerly parsing the ~1M vertices would cost seconds.
   */
  geometry(index) {
    const cached = this.geometryCache.get(index);
    if (cached !== undefined) return cached;

    const start = this.geomIndex[index];
    const end = this.geomIndex[index + 1];
    if (start === end) {
      this.geometryCache.set(index, null);
      return null;
    }

    const { view } = this;
    let pos = this.geomOffset + start;
    const bbox = [
      view.getInt32(pos, true),
      view.getInt32(pos + 4, true),
      view.getInt32(pos + 8, true),
      view.getInt32(pos + 12, true),
    ];
    pos += 16;

    // Counts are plain unsigned varints; coordinates are zigzagged. Mixing the
    // two up doubles every ring count and runs the decoder off the end.
    const readUvarint = () => {
      let result = 0;
      let shift = 0;
      for (;;) {
        const byte = view.getUint8(pos);
        pos += 1;
        result += (byte & 0x7f) * 2 ** shift;
        if ((byte & 0x80) === 0) return result;
        shift += 7;
      }
    };
    const readSvarint = () => {
      const value = readUvarint();
      return value % 2 === 0 ? value / 2 : -(value + 1) / 2;
    };

    const polygonCount = readUvarint();
    const polygons = [];
    for (let p = 0; p < polygonCount; p += 1) {
      const ringCount = readUvarint();
      const rings = [];
      for (let r = 0; r < ringCount; r += 1) {
        const pointCount = readUvarint();
        const xs = new Float64Array(pointCount);
        const ys = new Float64Array(pointCount);
        let x = 0;
        let y = 0;
        for (let i = 0; i < pointCount; i += 1) {
          x += readSvarint();
          y += readSvarint();
          xs[i] = x;
          ys[i] = y;
        }
        rings.push([xs, ys]);
      }
      polygons.push(rings);
    }

    const decoded = { bbox, polygons };
    this.geometryCache.set(index, decoded);
    return decoded;
  }

  /** Even-odd ray casting, exactly as SPEC §3.3 defines it. */
  static pointInRing(xs, ys, x, y) {
    let inside = false;
    const n = xs.length;
    let j = n - 1;
    for (let i = 0; i < n; i += 1) {
      const yi = ys[i];
      const yj = ys[j];
      if (yi > y !== yj > y) {
        if (x < xs[i] + ((y - yi) * (xs[j] - xs[i])) / (yj - yi)) {
          inside = !inside;
        }
      }
      j = i;
    }
    return inside;
  }

  contains(index, qx, qy) {
    const decoded = this.geometry(index);
    if (decoded === null) return false;
    const { bbox, polygons } = decoded;
    if (qx < bbox[0] || qx > bbox[2] || qy < bbox[1] || qy > bbox[3]) return false;
    for (const rings of polygons) {
      const [outerXs, outerYs] = rings[0];
      if (!GTCData.pointInRing(outerXs, outerYs, qx, qy)) continue;
      let inHole = false;
      for (let h = 1; h < rings.length; h += 1) {
        if (GTCData.pointInRing(rings[h][0], rings[h][1], qx, qy)) {
          inHole = true;
          break;
        }
      }
      if (!inHole) return true;
    }
    return false;
  }

  #locateIn(grid, lat, lng) {
    if (!this.hasGeometry) {
      throw new GeometryUnavailable(
        "this dataset carries no geometry; use a lite or full .gtc",
      );
    }
    const col = Math.floor((lng - this.originLng) / this.gridStep);
    const row = Math.floor((lat - this.originLat) / this.gridStep);
    if (col < 0 || col >= this.gridWidth || row < 0 || row >= this.gridHeight) {
      return null;
    }
    const cellId = row * this.gridWidth + col;

    const i = upperBound(grid.runStart, cellId);
    if (i >= 0 && cellId < grid.runStart[i] + grid.runLength[i]) {
      return grid.runValue[i];
    }

    const j = exactSearch(grid.mixedCells, cellId);
    if (j < 0) return null;

    const qx = lng * this.scale;
    const qy = lat * this.scale;
    // Candidates were written in ascending adcode order (SPEC §3.4).
    for (let slot = grid.mixedPtrs[j]; slot < grid.mixedPtrs[j + 1]; slot += 1) {
      const index = grid.mixedLists[slot];
      if (this.contains(index, qx, qy)) return index;
    }
    return null;
  }

  /** Record index of the district containing the point, or null. */
  locate(lat, lng) {
    return this.#locateIn(this.districtGrid, lat, lng);
  }

  /**
   * Record index of the province containing the point, or null.
   *
   * Needed wherever no district covers the point: Taiwan is published at
   * province level only, and coastal gaps leave slivers between districts.
   */
  locateProvince(lat, lng) {
    return this.#locateIn(this.provinceGrid, lat, lng);
  }
}
