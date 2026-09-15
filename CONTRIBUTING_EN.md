<!-- translation-of: CONTRIBUTING.md sha256:39ddda9b0250de83e3c5cf41de8a747109e86f8d826e18459502e84d2c81b2ed -->

# Contributing

> **[CONTRIBUTING.md](CONTRIBUTING.md) (Chinese) is normative.** Where the two
> disagree, the Chinese text wins. CI fails if one changes without the other.

Three implementations in three languages read one dataset and are held to one
contract. That makes the workflow different from a single-language project:
**a behaviour change starts in the contract, the contract change reaches every
implementation, and every implementation change regenerates the tests.**
Organised below by what you are trying to do.

## Setup

```bash
git clone https://github.com/13Cohen/GeoToolCN && cd GeoToolCN
pip install -e ".[dev]"                     # Python, tests, and geopandas for building data
node packages/node/scripts/sync-data.mjs    # Node's copy of the dataset (gitignored)
bash packages/go/scripts/sync-data.sh       # Go's copy (committed; this confirms it is current)
```

Touching only Python needs neither Node nor Go — but **any commit that changes
behaviour fails the other two implementations' conformance run**, so CI runs
all three. To run everything locally:

```bash
pytest                                                                   # 166 tests
python conformance/run.py                                                # Python, 38k cases
python conformance/run.py --adapter cmd --cmd "node conformance/adapters/node.mjs"
cd packages/go && CGO_ENABLED=0 go build -o /tmp/gtc-adapter ./cmd/conformance-adapter && cd ../..
python conformance/run.py --adapter cmd --cmd /tmp/gtc-adapter
cd packages/node && node --test && cd ../..
cd packages/go && CGO_ENABLED=0 go test ./... && cd ../..
```

## I want to fix a bug

First decide which kind it is:

**The result is wrong and SPEC is right** — one implementation is not following
the contract. Fix that implementation, add a reproducing case to its own unit
tests, run the conformance suite. SPEC and the suite stay as they are.

**The result is wrong and so is SPEC (or SPEC is silent)** — that is a
behaviour change; see the next section.

**All three implementations agree with each other but not with the geopandas
reference** — run the differential test to see how far apart they are:

```bash
python conformance/differential.py -n 200000
```

Below one in a thousand and concentrated at boundaries is quantisation
(1e-5 degrees ≈ 1.1 m) and expected; anything else is a bug.

## I want to change a behaviour

The order matters, and each step has a CI gate:

1. **Edit `SPEC.md`.** Behaviour is defined there and nowhere else; write the
   new behaviour down first. Then update `SPEC_EN.md` and run
   `python scripts/check_translations.py --update` to refresh the hash — CI
   blocks otherwise.

2. **Change the Python implementation** (`GeoToolCN/`). It is what the suite is
   generated from, so it goes first.

3. **Regenerate the conformance suite:**

   ```bash
   python conformance/generate.py
   git diff --stat conformance/
   ```

   Review the diff: the number of changed cases should match the footprint you
   expected. If you changed search ordering, `reverse.jsonl` should not have
   moved; if it did, you changed something else too.

4. **Change the Node and Go implementations** and run the suite until all
   three pass.

5. **If the old behaviour was "different but defensible"** (say, a sort order
   where both choices are reasonable), register a `DIV-xxx` entry in
   `conformance/known-divergences.yaml` with the old behaviour, the new one and
   the reason. Older implementations can run the suite with `--allow DIV-xxx`.

6. **Record it in `CHANGELOG.md`.** A change that alters the result for an
   existing coordinate goes under "Result changes".

## I want to update the data

```bash
python scripts/fetch_datav_geojson.py       # download, GCJ-02 → WGS-84, writes DATA_UPDATE_REPORT.md; writes nothing if any region failed
python pipeline/build_gtc.py                # build GeoToolCN/data/china.full.gtc
python scripts/validate_gtc.py --round-trip # validate the artifact
bash packages/go/scripts/sync-data.sh       # Go's copy must be committed; CI compares it byte for byte
python conformance/generate.py              # regenerate the suite
pytest                                      # invariants carry no golden values and must still pass
python conformance/differential.py          # against the geopandas reference; CI runs this too
```

Review the added and removed divisions in `DATA_UPDATE_REPORT.md`. A failure in
`tests/test_invariants.py` means the new data is itself inconsistent (a
district with no parent, say) — the test is not what needs changing.

## I want to add a language

See [PORTING_EN.md](PORTING_EN.md): about 600 lines and one adapter; pass the
38,000+ cases and it can be merged. The full acceptance checklist is there.

## I want to add a test

First decide which layer it belongs to:

| Layer | Where | When |
|-------|-------|------|
| L0 artifact | `scripts/validate_gtc.py` | Structural properties of the `.gtc` file itself |
| L1 invariants | `tests/test_invariants.py` | Properties that hold for **every** division; no literal values |
| L2 conformance | `conformance/generate.py` | Input/output pairs every language must agree on |
| L3 differential | `conformance/differential.py` | Against the geopandas reference |
| L4 unit | `tests/`, `packages/*/…_test` | One implementation's internals and error paths |
| L5 post-release | `scripts/verify_published.py` | Properties observable only from an installed artifact |

**Then mutation-test it:** deliberately break the implementation and confirm
the new test goes red. The number of failures should match the footprint of the
fault — if you changed how 34 two-level adcodes are handled, exactly 34 cases
should fail. `PORTING_EN.md` lists the mutations already measured.

## Commits and PRs

- One PR, one thing. Keep behaviour changes and drive-by formatting apart.
- Commit messages say **why**, not what the diff already shows. What led you to
  the problem; which alternatives you ruled out.
- `README.md` has CRLF line endings (historical); `scripts/check_line_endings.py`
  guards them. Preserve them when editing it with a script.
- `master` merges by squash. **Branching from an already-merged branch
  conflicts** — branch from the latest `master`.

## Releasing

Maintainers only; see [docs/RELEASING.md](docs/RELEASING.md).
