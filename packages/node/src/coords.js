// Coordinate conversions between WGS-84, GCJ-02 (国测局 / 高德 / 腾讯) and
// BD-09 (百度). Pure maths, no data. SPEC.md §2.11.
//
// NOTE the argument order: the six conversions take (lng, lat) — longitude
// first — while distance() takes latitude first, matching the GeoTool methods.
// The inconsistency is inherited from the Python package and preserved so the
// two agree. Passing a conversion (lat, lng) does not raise: the swapped
// longitude falls outside the China bounding box, so the input comes straight
// back and the mistake is silent.

const A = 6378245.0;
const EE = 0.00669342162296594;
const X_PI = (Math.PI * 3000.0) / 180.0;

const LNG_MIN = 72.004;
const LNG_MAX = 137.8347;
const LAT_MIN = 0.8293;
const LAT_MAX = 55.8271;

const EARTH_RADIUS_KM = 6371.0;

function outOfChina(lng, lat) {
  return !(lng > LNG_MIN && lng < LNG_MAX && lat > LAT_MIN && lat < LAT_MAX);
}

function transformLat(x, y) {
  let ret =
    -100.0 +
    2.0 * x +
    3.0 * y +
    0.2 * y * y +
    0.1 * x * y +
    0.2 * Math.sqrt(Math.abs(x));
  ret += ((20.0 * Math.sin(6.0 * x * Math.PI) + 20.0 * Math.sin(2.0 * x * Math.PI)) * 2.0) / 3.0;
  ret += ((20.0 * Math.sin(y * Math.PI) + 40.0 * Math.sin((y / 3.0) * Math.PI)) * 2.0) / 3.0;
  ret += ((160.0 * Math.sin((y / 12.0) * Math.PI) + 320 * Math.sin((y * Math.PI) / 30.0)) * 2.0) / 3.0;
  return ret;
}

function transformLng(x, y) {
  let ret =
    300.0 + x + 2.0 * y + 0.1 * x * x + 0.1 * x * y + 0.1 * Math.sqrt(Math.abs(x));
  ret += ((20.0 * Math.sin(6.0 * x * Math.PI) + 20.0 * Math.sin(2.0 * x * Math.PI)) * 2.0) / 3.0;
  ret += ((20.0 * Math.sin(x * Math.PI) + 40.0 * Math.sin((x / 3.0) * Math.PI)) * 2.0) / 3.0;
  ret += ((150.0 * Math.sin((x / 12.0) * Math.PI) + 300.0 * Math.sin((x / 30.0) * Math.PI)) * 2.0) / 3.0;
  return ret;
}

function delta(lng, lat) {
  let dLat = transformLat(lng - 105.0, lat - 35.0);
  let dLng = transformLng(lng - 105.0, lat - 35.0);
  const radLat = (lat / 180.0) * Math.PI;
  let magic = Math.sin(radLat);
  magic = 1 - EE * magic * magic;
  const sqrtMagic = Math.sqrt(magic);
  dLat = (dLat * 180.0) / (((A * (1 - EE)) / (magic * sqrtMagic)) * Math.PI);
  dLng = (dLng * 180.0) / ((A / sqrtMagic) * Math.cos(radLat) * Math.PI);
  return [dLng, dLat];
}

/** WGS-84 → GCJ-02. Returns [lng, lat]. */
export function wgs84ToGcj02(lng, lat) {
  if (outOfChina(lng, lat)) return [lng, lat];
  const [dLng, dLat] = delta(lng, lat);
  return [lng + dLng, lat + dLat];
}

/** GCJ-02 → WGS-84. A single-step inverse, so the round trip loses ~1–5 m. */
export function gcj02ToWgs84(lng, lat) {
  if (outOfChina(lng, lat)) return [lng, lat];
  const [dLng, dLat] = delta(lng, lat);
  return [lng - dLng, lat - dLat];
}

/** GCJ-02 → BD-09. */
export function gcj02ToBd09(lng, lat) {
  const z = Math.sqrt(lng * lng + lat * lat) + 0.00002 * Math.sin(lat * X_PI);
  const theta = Math.atan2(lat, lng) + 0.000003 * Math.cos(lng * X_PI);
  return [z * Math.cos(theta) + 0.0065, z * Math.sin(theta) + 0.006];
}

/** BD-09 → GCJ-02. */
export function bd09ToGcj02(lng, lat) {
  const x = lng - 0.0065;
  const y = lat - 0.006;
  const z = Math.sqrt(x * x + y * y) - 0.00002 * Math.sin(y * X_PI);
  const theta = Math.atan2(y, x) - 0.000003 * Math.cos(x * X_PI);
  return [z * Math.cos(theta), z * Math.sin(theta)];
}

/** WGS-84 → BD-09. */
export function wgs84ToBd09(lng, lat) {
  const [gLng, gLat] = wgs84ToGcj02(lng, lat);
  return gcj02ToBd09(gLng, gLat);
}

/** BD-09 → WGS-84. */
export function bd09ToWgs84(lng, lat) {
  const [gLng, gLat] = bd09ToGcj02(lng, lat);
  return gcj02ToWgs84(gLng, gLat);
}

/** Great-circle distance in kilometres. Latitude first, unlike the conversions. */
export function distance(lat1, lng1, lat2, lng2) {
  const toRad = (deg) => (deg * Math.PI) / 180.0;
  const dLat = toRad(lat2 - lat1);
  const dLng = toRad(lng2 - lng1);
  const a =
    Math.sin(dLat / 2) ** 2 +
    Math.cos(toRad(lat1)) * Math.cos(toRad(lat2)) * Math.sin(dLng / 2) ** 2;
  return 2 * EARTH_RADIUS_KM * Math.asin(Math.min(1, Math.sqrt(a)));
}
