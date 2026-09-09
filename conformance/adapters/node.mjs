// Conformance adapter for @geotoolcn/core.
//
//   python conformance/run.py --adapter cmd --cmd "node conformance/adapters/node.mjs"
//
// Reads one JSON request per line on stdin, writes one JSON response per line
// on stdout. Adding a language means writing a file like this one.

import { createHash } from "node:crypto";
import { createInterface } from "node:readline";

import {
  GeoTool,
  bd09ToGcj02,
  bd09ToWgs84,
  distance,
  gcj02ToBd09,
  gcj02ToWgs84,
  getAdministrativeTree,
  wgs84ToBd09,
  wgs84ToGcj02,
} from "../../packages/node/src/index.js";

const geo = new GeoTool();

const CONVERSIONS = {
  wgs84_to_gcj02: wgs84ToGcj02,
  gcj02_to_wgs84: gcj02ToWgs84,
  gcj02_to_bd09: gcj02ToBd09,
  bd09_to_gcj02: bd09ToGcj02,
  wgs84_to_bd09: wgs84ToBd09,
  bd09_to_wgs84: bd09ToWgs84,
};

const chain = (result) =>
  result === null
    ? null
    : [
        result.province?.code ?? null,
        result.city?.code ?? null,
        result.district?.code ?? null,
      ];

/**
 * Serialise the way Python's json.dumps(sort_keys=True, separators=(",",":"),
 * ensure_ascii=False) does, so the tree hash can be compared across languages.
 */
function canonical(value) {
  if (value === null || typeof value !== "object") return JSON.stringify(value);
  if (Array.isArray(value)) return `[${value.map(canonical).join(",")}]`;
  const keys = Object.keys(value).sort();
  return `{${keys.map((k) => `${JSON.stringify(k)}:${canonical(value[k])}`).join(",")}}`;
}

function handle(op, args) {
  switch (op) {
    case "reverse":
      return chain(geo.reverse(args[0], args[1]));
    case "lookup_adcode":
      return chain(geo.lookupAdcode(args[0]));
    case "search":
      return geo.search(args[0], args[1]).map((r) => r.code);
    case "is_in_china":
      return geo.isInChina(args[0], args[1]);
    case "is_in_region":
      return geo.isInRegion(args[0], args[1], args[2]);
    case "distance":
      return distance(args[0], args[1], args[2], args[3]);
    case "tree_sha256":
      return createHash("sha256")
        .update(canonical(getAdministrativeTree()), "utf-8")
        .digest("hex");
    default: {
      const fn = CONVERSIONS[op];
      if (!fn) throw new Error(`unknown op: ${op}`);
      return fn(args[0], args[1]);
    }
  }
}

const lines = createInterface({ input: process.stdin, terminal: false });
for await (const line of lines) {
  if (!line.trim()) continue;
  const { op, args } = JSON.parse(line);
  let response;
  try {
    response = { ok: handle(op, args) };
  } catch (error) {
    response = { error: String(error?.message ?? error) };
  }
  process.stdout.write(`${JSON.stringify(response)}\n`);
}
