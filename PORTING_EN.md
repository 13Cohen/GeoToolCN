<!-- translation-of: PORTING.md sha256:657456b04f1d77e82899cb6be523e260751260a9b592f848ecaab1a8ca11c368 -->

# Porting to a new language

> **[PORTING.md](PORTING.md) (Chinese) is normative.** Where the two disagree,
> the Chinese text wins. CI fails if one changes without the other.

Porting GeoToolCN takes roughly **600 lines**, plus an adapter. This page covers
what to write and how to prove you got it right.

Existing implementations to work from:

| Language | Location | Lines (excluding comments) |
|----------|----------|---------------------------|
| Python | `GeoToolCN/_gtc.py` + `core.py` | ~600 |
| JavaScript | `packages/node/src/` | ~600 |
| Go | `packages/go/*.go` | ~700 |

## Why it is this short

All the expensive work already happened at build time. The `.gtc` carries a
precomputed grid index: **about 77% of lookups hit the table and touch no
geometry at all**, and the rest average 2 candidate polygons.

So you need **no** R-tree, no GEOS, no geometry library, and no native bindings.
What you need is: read a binary, binary search, ray casting.

## Steps

### 1. Read SPEC_EN.md

[`SPEC_EN.md`](SPEC_EN.md) is the contract (`SPEC.md` in Chinese is normative).
§4 defines the binary format, §2 the API behaviour, and §3 the rules that drift
silently across languages if left unstated.

**§3.1 rounding especially**: Python's `round()` is banker's rounding and
JavaScript's `Math.round` is half-up; neither matches the specification.

### 2. Implement the reader

Parse the `.gtc` per §4. A workable order:

1. Header and section table (32-byte header, 24 bytes per section)
2. META (division metadata) and NAMES (UTF-8 string pool)
3. The grid index (two of them: district and province)
4. Lazy geometry decoding

**The three traps every existing port hit:**

- **Counts are plain varints; coordinates are zigzag varints** (§4.5). Zigzagging
  the counts too doubles every ring count and runs the decoder past the end of
  the section. That is exactly how the prototype broke.
- **Integer tables may be misaligned.** Offsets within the file are not
  guaranteed 4-byte aligned, and reinterpreting the bytes as a u32 array crashes
  in most languages. Copy instead — 500k entries costs about a millisecond.
- **Decode geometry lazily.** Parsing all ~1M vertices up front costs seconds,
  and most lookups never need any of it.

### 3. Implement the API

Follow §2 function by function. The core is `reverse`:

```
district hit -> derive province and city from the district's adcode
no hit       -> consult the province grid; city only when the province is a
                municipality or SAR
```

**Do not run three independent point-in-polygon tests, one per layer.** The
source data contradicts itself in places — 加格达奇区 is administered by
Heilongjiang but sits inside Inner Mongolia's outline, and several district
polygons extend past their province onto offshore islands. Independent lookups
produce self-contradictory results.

### 4. Write an adapter

Put it in `conformance/adapters/<lang>.<ext>`. The protocol is deliberately
tiny: one JSON request per line on stdin, one JSON response per line on stdout.

```
-> {"op":"reverse","args":[39.9042,116.4074]}
<- {"ok":["110000","110100","110101"]}
<- {"error":"invalid adcode"}
```

Ops to support: `reverse`, `lookup_adcode`, `search`, `is_in_china`,
`is_in_region`, `distance`, `tree_sha256`, and the six coordinate conversions
(snake_case op names, e.g. `wgs84_to_gcj02`).

⚠️ Beware "omit empty" serialisation: Go's `omitempty` and similar defaults
swallow `false` and empty arrays, turning `is_in_china=false` into a missing
field.

### 5. Run the conformance suite

```bash
python conformance/run.py --adapter cmd --cmd "<your adapter command>"
```

35,000+ cases, and **all of them must pass**. Failures are grouped by tag,
because a port is usually wrong about a whole category of input — boundaries,
municipalities — rather than about scattered points.

## How to know you got it right

Passing is not enough — **a suite that tests nothing also passes**. Inject
faults deliberately and confirm the suite catches them:

| Injected fault | Measured on the three existing implementations |
|----------------|-----------------------------------------------|
| Zigzag decode off by one | 1,828 cases fail |
| Grid cell `floor` → `round` | 560 fail |
| Substring → prefix matching | 177 fail |
| Search result order reversed | 70 fail |

If your implementation survives any of these, the suite is not covering that
part of your code — tell us, because that is a gap in the suite.

**Two known survivors** (do not worry about these):

- Ray casting `<` → `<=`: only affects points exactly on an edge, where SPEC §3.3
  explicitly declines to assert.
- Truncating a GCJ-02 constant: moves output by less than 0.1 mm, below the
  comparison tolerance. **Constant correctness can only be caught by review** —
  compare the table in SPEC §2.11 character by character.

## The hardest thing to match: the administrative tree hash

The tree's JSON shape must match **exactly** (SPEC §1.3):

- Province and city nodes: `children` is **always present**, `[]` when empty
- Districts (leaves): `children` is **absent** — not `[]`, not `null`

Go's `json:"children,omitempty"` drops empty arrays too, so you need custom
serialisation to distinguish "nil" from "empty but non-nil".

The hash is the SHA-256 of canonical JSON (keys sorted, no whitespace, non-ASCII
unescaped) encoded as UTF-8. Note that Go's `encoding/json` escapes `<`, `>` and
`&` by default — use `SetEscapeHTML(false)`.

## Acceptance checklist

To have an implementation merged and listed in the docs:

```
□ Implements the full API contract in SPEC §2
□ Passes 100% of the 35,000+ conformance cases
□ Adapter lives in conformance/adapters/
□ A row added to conformance-matrix in .github/workflows/test.yml
□ Unit tests in the language's idiomatic framework (these do not replace
  conformance)
□ README covering installation
□ Zero runtime dependencies — this is the project's central promise
```

You are **not** expected to understand the whole design. Passing conformance is
objective proof that the implementation is correct.

## The dataset

Avoid committing the `.gtc` once per language where you can — 6 MB × languages
adds up. After building:

```bash
python pipeline/build_gtc.py            # needs geopandas, build time only
cp GeoToolCN/data/china.full.gtc packages/<your language>/data/
```

**Whether to gitignore that copy depends on how your ecosystem distributes:**

- **Central registry** (PyPI, npm, crates.io, Maven, …): gitignore it. The data
  is injected into the artifact at packaging time, so one copy in the repository
  is enough.
- **Resolved straight from git** (Go): **it must be committed.** `go get` only
  gets what git holds, and `go:embed` cannot reach outside the module directory.
  `packages/go/data/china.full.gtc` is therefore the one duplicated copy in this
  repository.

How to tell: extract `git ls-files packages/<your language>` on its own and see
whether it builds.

## Questions

Open an issue: https://github.com/13Cohen/GeoToolCN/issues

If the specification is ambiguous, that is a bug in the specification, not in
your port — please report it and we will make it precise. Every exact sentence
in there is exact because some implementation got it wrong first.
