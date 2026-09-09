// Copies the built dataset in from the Python package.
//
// The .gtc is a build artifact shared by every language binding, so it lives in
// one place in the repository rather than being committed once per package.
// Rebuilding it needs geopandas; copying it does not, which is what keeps a
// fresh clone able to run the Node tests.
import { copyFileSync, mkdirSync, existsSync } from "node:fs";
import { dirname, join } from "node:path";
import { fileURLToPath } from "node:url";

const here = dirname(fileURLToPath(import.meta.url));
const source = join(here, "..", "..", "..", "GeoToolCN", "data");
const target = join(here, "..", "data");

const files = ["china.full.gtc", "china_admin.json", "DATA_VERSION.json"];

mkdirSync(target, { recursive: true });
for (const name of files) {
  const from = join(source, name);
  if (!existsSync(from)) {
    console.error(`missing ${from} — run: python pipeline/build_gtc.py`);
    process.exit(1);
  }
  copyFileSync(from, join(target, name));
  console.log(`synced ${name}`);
}
