// Idiomatic smoke tests. Correctness at scale is the conformance suite's job —
// these exist so `npm test` says something useful without a Python toolchain.
import assert from "node:assert/strict";
import { test } from "node:test";

import {
  GeoTool,
  distance,
  gcj02ToWgs84,
  getAdministrativeTree,
  isInRegion,
  lookupAdcode,
  reverse,
  search,
  wgs84ToGcj02,
} from "../src/index.js";

test("reverse resolves a city centre", () => {
  const r = reverse(39.9042, 116.4074);
  assert.equal(r.province.name, "北京市");
  assert.equal(r.district.code, "110101");
  // Municipalities report the province as their city.
  assert.equal(r.city.code, "110000");
  assert.equal(r.city.level, "city");
});

test("reverse returns nulls outside China", () => {
  const r = reverse(35.6762, 139.6503);
  assert.equal(r.province, null);
  assert.equal(r.district, null);
});

test("the hierarchy is always self-consistent", () => {
  // 加格达奇区 is administered by 黑龙江 but sits inside 内蒙古's outline.
  const r = reverse(50.37295, 124.16537);
  assert.equal(r.province.code, "230000");
  assert.equal(r.district.code, "232718");
  assert.equal(r.province.code.slice(0, 2), r.district.code.slice(0, 2));
});

test("islands resolve a province", () => {
  const r = reverse(30.66457, 122.56396);
  assert.equal(r.province.name, "浙江省");
  assert.equal(r.district.name, "嵊泗县");
});

test("search disambiguates by parent", () => {
  assert.equal(search("朝阳区", { level: "district" }).length, 2);
  assert.deepEqual(
    search("朝阳区", { province: "北京市" }).map((r) => r.code),
    ["110105"],
  );
  // Filtering is by adcode, not geometry: an island's representative point
  // lies outside its own province's outline.
  assert.deepEqual(
    search("嵊泗县", { province: "浙江省" }).map((r) => r.code),
    ["330922"],
  );
});

test("search treats the query literally, never as a regex", () => {
  assert.deepEqual(search("东.区", { level: "district" }), []);
  assert.deepEqual(search("["), []);
});

test("search results are sorted by level then adcode", () => {
  const codes = search("朝阳区", { level: "district" }).map((r) => r.code);
  assert.deepEqual(codes, [...codes].sort());
});

test("lookupAdcode handles province-governed county-level divisions", () => {
  // 济源市 is its own city; adcode[:4] + "00" would give the nonexistent 419000.
  assert.equal(lookupAdcode("419001").city.name, "济源市");
  // 东莞市 has no subdivisions and appears at both levels under one code.
  assert.equal(lookupAdcode("441900").district.name, "东莞市");
});

test("isInRegion works for Taiwan, which has no districts", () => {
  assert.equal(isInRegion(25.03, 121.56, "710000"), true);
  assert.equal(isInRegion(39.9042, 116.4074, "710000"), false);
});

test("isInRegion rejects unknown adcodes", () => {
  assert.throws(() => isInRegion(39.9, 116.4, "999999"), TypeError);
  assert.throws(() => isInRegion(39.9, 116.4, "xyz"), TypeError);
});

test("the tree has one path per district", () => {
  const tree = getAdministrativeTree();
  assert.equal(tree.length, 34);
  const leaves = tree
    .flatMap((p) => p.children)
    .flatMap((c) => c.children ?? [])
    .map((d) => d.value);
  assert.equal(leaves.length, 2874);
  assert.equal(new Set(leaves).size, 2874, "a district is reachable twice");
});

test("coordinate conversions take longitude first and round-trip", () => {
  const [gLng, gLat] = wgs84ToGcj02(116.4074, 39.9042);
  assert.ok(Math.abs(gLng - 116.4074) < 0.01);
  const [wLng, wLat] = gcj02ToWgs84(gLng, gLat);
  // A single-step inverse, so the round trip is lossy by a few metres.
  assert.ok(distance(39.9042, 116.4074, wLat, wLng) * 1000 < 6);
});

test("conversions pass through outside China", () => {
  assert.deepEqual(wgs84ToGcj02(139.6503, 35.6762), [139.6503, 35.6762]);
});

test("a shared instance is reused across module-level calls", () => {
  const explicit = new GeoTool();
  assert.deepEqual(explicit.reverse(31.2304, 121.4737), reverse(31.2304, 121.4737));
});
