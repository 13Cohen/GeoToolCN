<!-- translation-of: docs/CLI.md sha256:9d39657c93ba84608891effd1a0acf2993fd2adc88b40df2780f331f7707eed8 -->

# The geotoolcn CLI and HTTP server

> **[CLI.md](CLI.md) (Chinese) is normative.** Where the two disagree, the
> Chinese text wins. CI fails if one changes without the other.

One static binary with the whole dataset inside, for wherever there is no
language binding: shell scripts, PHP, Ruby, Java, C# — anything that can make an
HTTP request or spawn a process. It is a thin wrapper over the
[Go implementation](../packages/go/README.md) and returns exactly what the
Python, Node and Go libraries return.

## Installation

**Download a binary** ([Releases](https://github.com/13Cohen/GeoToolCN/releases),
tags prefixed `cli-v`):

| Platform | File |
|----------|------|
| Linux x86-64 / ARM64 | `geotoolcn-linux-amd64` / `geotoolcn-linux-arm64` |
| macOS Intel / Apple Silicon | `geotoolcn-darwin-amd64` / `geotoolcn-darwin-arm64` |
| Windows x86-64 | `geotoolcn-windows-amd64.exe` |

```bash
curl -Lo geotoolcn https://github.com/13Cohen/GeoToolCN/releases/latest/download/geotoolcn-linux-amd64
chmod +x geotoolcn
```

**Container image** (`linux/amd64`, `linux/arm64`, built on `scratch`, about 18 MB):

```bash
docker run --rm -p 8080:8080 ghcr.io/13cohen/geotoolcn            # HTTP server
docker run --rm ghcr.io/13cohen/geotoolcn reverse 39.9042 116.4074   # or a subcommand directly
```

**From source** (Go 1.21+, no cgo):

```bash
go install github.com/13Cohen/GeoToolCN/packages/go/v3/cmd/geotoolcn@latest
```

## Conventions

Every subcommand **writes JSON to stdout**, two-space indented, non-ASCII left
unescaped, ready for `| jq`.

On failure **stdout stays empty** and the error goes to stderr as JSON:
`{"error":"..."}`. `geotoolcn ... | jq` is therefore never fed half a result.

Exit codes:

| Code | Meaning |
|------|---------|
| `0` | Success |
| `1` | Runtime failure: coordinate unparseable or out of range, unknown adcode, unsupported conversion, unknown option |
| `2` | Usage error: missing or unknown subcommand |

Coordinates must be finite and within `[-90, 90]` × `[-180, 180]`: `NaN`, `Inf`
and `91` all exit `1` rather than answer with the empty "outside China" result —
the two should not look alike to a caller.

## Subcommands

### `reverse <lat> <lng>`

Coordinate → province / city / district. **Latitude first.**

```bash
$ geotoolcn reverse 39.9042 116.4074
{
  "province": { "name": "北京市", "code": "110000", "level": "province", "latitude": 40.2481, "longitude": 116.632868 },
  "city":     { "name": "北京市", "code": "110000", "level": "city",     "latitude": 40.2481, "longitude": 116.632868 },
  "district": { "name": "东城区", "code": "110101", "level": "district", "latitude": 39.917839, "longitude": 116.416357 }
}

$ geotoolcn reverse 39.9042 116.4074 | jq -r .district.name
东城区
```

Outside China all three are `null` and the exit code is still `0` — that is a
valid answer, not an error:

```bash
$ geotoolcn reverse 0 0
{ "province": null, "city": null, "district": null }
```

### `lookup <adcode>`

adcode → the full chain. Same shape as `reverse`.

```bash
$ geotoolcn lookup 419001            # 济源市, province-governed: its city is itself
{
  "province": { "name": "河南省", "code": "410000", ... },
  "city":     { "name": "济源市", "code": "419001", ... },
  "district": { "name": "济源市", "code": "419001", ... }
}

$ geotoolcn lookup 999999
{"error":"未找到 adcode \"999999\""}      # → stderr, exit 1
```

### `search <query> [--level L] [--province P] [--city C] [--exact]`

Search by name or adcode. **`<query>` must come first**, flags after it.

| Flag | Meaning |
|------|---------|
| `--level` | Restrict to `province` / `city` / `district` |
| `--province` | Restrict to a province, by name or adcode |
| `--city` | Restrict to a city, by name or adcode |
| `--exact` | Disable substring (fuzzy) matching |

```bash
$ geotoolcn search 朝阳区                          # one in Beijing, one in Changchun
$ geotoolcn search 朝阳区 --province 北京市         # Beijing only
$ geotoolcn search 深圳 --exact                    # exact "深圳": 0 results (the name is "深圳市")
$ geotoolcn search 440300                          # by adcode
```

The query is matched **literally** — `.`, `*`, `[` are not wildcards. No
results prints `[]` (not `null`) with exit code `0`; so does a `--province` /
`--city` that names nothing. The query must come first: a query starting with
`-` is treated as a misplaced flag and exits `1`. `--level` accepts only
`province` / `city` / `district`.

### `tree`

The province → city → district tree, for cascader widgets.

```bash
$ geotoolcn tree | jq '.[0]'
{
  "value": "110000",
  "label": "北京市",
  "children": [
    { "value": "110000", "label": "北京市", "children": [ { "value": "110101", "label": "东城区" }, ... ] }
  ]
}
```

Province and city nodes always carry `children` (possibly empty); district
nodes do not have the field. Municipalities and SARs use the province code for
their city node. 34 province-level divisions, 2874 districts.

### `convert <from> <to> <lng> <lat>`

Coordinate system conversion. `from` / `to` are `wgs84` / `gcj02` / `bd09`,
case-insensitive.

> ⚠️ **Longitude first**, as in GIS convention; `reverse` takes latitude first.
> Swapping them does not raise — the swapped coordinate falls outside China and
> is returned unchanged.

```bash
$ geotoolcn convert wgs84 gcj02 116.4074 39.9042
{ "lng": 116.41364225378803, "lat": 39.90560334316507 }
```

All six directions are supported. Same-system conversions such as
`wgs84 → wgs84` are not, and exit `1`.

### `serve [--addr :8080]`

Start the HTTP server, described below. The route list goes to stderr; stdout
stays clean.

### `version` / `help`

`version` prints `{"version": "3.0.0"}`; `help` prints usage. `--version`,
`-v`, `--help` and `-h` are aliases. The version is injected from the tag at
release time; a binary from `go install ...@v3.x.y` reads the module version Go
recorded; a plain `go build` from an untagged tree reports `dev`. None of these
four subcommands load the dataset.

## HTTP server

```bash
geotoolcn serve --addr :8080
```

Every response is `Content-Type: application/json; charset=utf-8` with non-ASCII
unescaped — errors included: an unknown path is `404 {"error":…}`, a method
other than `GET` / `HEAD` is `405 {"error":…}`.

| Route | Parameters | Success | Failure |
|-------|------------|---------|---------|
| `/reverse` | `lat`, `lng` | `200` ReverseResult | `400` missing, non-numeric, `NaN`/`Inf`, or past ±90/±180 |
| `/lookup` | `adcode` | `200` ReverseResult | `400` missing `adcode`; `404` unknown |
| `/search` | `q`; optional `level`, `province`, `city`, `exact=1` | `200` Region[] (`[]` when empty) | `400` missing `q` or invalid `level` |
| `/regions` | `level` | `200` Region[] | `400` invalid level |
| `/tree` | — | `200` TreeNode[] | — |
| `/healthz` | — | `200` `{"status":"ok","version":"…"}` | — |

Failure bodies are `{"error":"..."}`.

```bash
$ curl 'localhost:8080/reverse?lat=39.9042&lng=116.4074' | jq -r .district.name
东城区

$ curl 'localhost:8080/search?q=朝阳区&province=北京市'
[{"name":"朝阳区","code":"110105","level":"district","latitude":39.948547,"longitude":116.530723}]

$ curl -i 'localhost:8080/lookup?adcode=999999'
HTTP/1.1 404 Not Found
{"error":"未找到 adcode \"999999\""}
```

Chinese parameters must be URL-encoded (`curl` and most HTTP clients do this;
take care when building URLs by hand).

### Deployment notes

- The server is stateless and the data read-only, so it scales horizontally;
  each instance holds about 30 MB resident
- Timeouts: `ReadHeaderTimeout` 5 s, `ReadTimeout` 10 s, `WriteTimeout` 30 s,
  `IdleTimeout` 120 s. The largest response (`/tree`, ~160 KB) is well inside
  the write budget; put a reverse proxy in front if you need longer keep-alives
- All geometry is decoded once at start-up (~100–200 ms), so there is no decode
  stall on the first request that reaches each region
- On `SIGTERM` / `SIGINT` the server stops accepting connections, drains
  in-flight requests (up to 10 s) and exits `0` — the signal a container
  runtime sends PID 1
- `--addr` defaults to `:8080`, i.e. every interface; use `--addr 127.0.0.1:8080`
  to try it locally
- The image runs as `nobody` (uid 65534) on `scratch`, with no shell; to debug,
  run a subcommand directly with `docker run ... reverse ...`
- `/healthz` is intended as the readiness probe

## Relationship to the libraries

The CLI calls the Go library and has no logic of its own. The library passes
the same 38,000+ conformance cases as the Python and Node implementations; the
CLI's tests (`packages/go/cmd/geotoolcn/main_test.go`) compare every subcommand
and route field by field against the library's return value, so the three
always agree.

After every release, `scripts/verify_published.py` downloads the binary from
the Release and the image from GHCR and runs every subcommand and route above.
