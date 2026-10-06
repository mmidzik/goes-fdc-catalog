# goes-fdc-catalog

A [Portolan](https://github.com/portolan-sdi/portolan-spec) catalog mirroring
**NOAA GOES-R ABI fire detections** (Fire/Hot Spot Characterization, FDC) as a
**virtual Zarr cube**.

Catalog metadata lives in this repository. The pixel data stays in NOAA's public
`noaa-goes*` buckets, and the catalog holds byte-range references to it. CI
validates every change to the metadata.

> **Status: pilot. Publishing to Source Cooperative is TODO.** Nothing is
> published. The storage path in `catalog.publish.yaml` is provisional, and no
> public catalog URL exists yet. Stage 1 runs locally on the Palisades fire
> window. See [Status and TODO](#status-and-todo).

- **Published catalog**: TODO, not on Source Cooperative yet
- **STAC root**: TODO, same
- **Browse it in the Portolan browser**: TODO, needs the published STAC root
- **Upstream**: https://registry.opendata.aws/noaa-goes/ (NOAA and NESDIS
  produce the data and remain the authoritative source)
- **Design**: [docs/architecture.md](docs/architecture.md)

This catalog is a reference implementation for
[portolan-spec#132](https://github.com/portolan-sdi/portolan-spec/issues/132),
which defers a normative Zarr profile until real Zarr datasets have been tested
in catalogs. The Zarr assets are outside the Portolan conformance surface.

Start with [docs/architecture.md](docs/architecture.md) for the data access
paths, components, flow, and open questions. The collection's own README and
AGENTS.md (what the data is, how to read it, the traps) arrive with the first
collection, under `catalog/goes-18/abi-l2-fdcc/`. Everything below is about how
this repository builds that catalog.

## What it will publish

One collection to start, `goes-18/abi-l2-fdcc`: the CONUS FDC product from
GOES-18. Each scan is a 1500 × 2500 grid on the ABI geostationary fixed grid,
about every 5 minutes. Five variables: `Mask`, `DQF`, `Power`, `Temp`, `Area`.

The pilot window is the Palisades fire, 2025-01-07 to 2025-01-31 (verify the end
date). The catalog later grows to the full GOES-18 record and to other
satellites, sectors, and products. Names follow
`abi-<level>-<product><sector>` under one sub-catalog per satellite.

The cube is published two ways, from the same references:

| Asset | Reader needs | Notes |
|---|---|---|
| Icechunk repo | `icechunk`, `zarr`, `xarray` | Transactional, appendable, detects a changed NOAA file |
| Kerchunk parquet | `fsspec`, `xarray` | No Icechunk dependency |

Both hold manifests, never pixels. Every read fetches chunk byte ranges from
NOAA.

## Design decisions worth knowing

**Virtual, not copied.** GOES FDC is a raster grid per scan with fire as a few
classes among many, so a fire-pixel table would drop the cloud, clear, and
quality pixels that detection validation needs. The cube keeps the full grid and
copies none of it. FIRMS converts to GeoParquet because its source is already a
list of detections. GOES FDC is not.

**No server.** Readers hit static files on Source Cooperative and NOAA's bucket.
The update job is a scheduled GitHub Action, not a hosted service. A later
event-driven version could subscribe to NOAA's `NewGOES18Object` SNS topic.

**Zarr outside conformance.** The collection says so. `docs/conformance.md`
records each validator finding the Zarr assets trigger and why it is accepted.

**No computed statistics.** A growing cube's statistics change on every append.
The collection carries `render` hints instead.

**Scaling stays on the arrays.** `scale_factor`, `add_offset` and `_FillValue`
survive virtualization. Read with `mask_and_scale=False` to get NOAA's raw
integers.

**The time axis is the file's `t`.** It falls mid-scan, between the start and end
stamps in the filename.

**One sub-catalog per satellite.** It sidesteps the East and West handoffs
(GOES-17 to GOES-18 on 2023-01-04, GOES-16 to GOES-19 on 2025-04-07).

## The pipeline

| Module | Does |
|---|---|
| `pipeline/src/goes_fdc/keys.py` | Parses NOAA key names and lists scans in a time window with an anonymous S3 listing. |
| `pipeline/src/goes_fdc/virtualize.py` | Reads each netCDF header with VirtualiZarr (`HDFParser`) and stacks scans along `time`. |
| `pipeline/src/goes_fdc/store.py` | Appends the new time steps to the Icechunk repo and exports Kerchunk parquet. |
| `pipeline/src/goes_fdc/cli.py` | The `goes-fdc build` command. Resumable: scans already in the store are skipped. |
| `tools/publish.py` | Syncs `catalog/` to the bucket. Template-provided; never widened beyond `catalog/`. |
| `tools/upload_data.py` | Uploads staged data files. Template-provided. |

```bash
uv sync
uv run goes-fdc build --start 2025-01-07T18:00 --end 2025-01-07T20:00 --out local/smoke
```

The bucket listing is the index. NOAA keys are
`ABI-L2-FDCC/<YYYY>/<DDD>/<HH>/<filename>`, and one anonymous list call per hour
prefix returns the scans. A second run with the same window adds nothing. NOAA
needs no credentials. A full backfill of GOES-18 FDCC since 2023-01-04 is about
400,000 files, header reads only. Its cost is not measured yet.

## Working on this repository

Python dependencies use [uv](https://docs.astral.sh/uv/). It creates `.venv` and
installs the locked versions.

```bash
uv sync
uv run pytest                          # unit tests, no network
uv run python tests/run_all.py         # gates: conformance, links, STAC validity
uv run rashid check catalog --schema   # the validator directly
uv run python tools/publish.py         # dry run
```

Data files never enter git. `.gitignore` blocks the common formats, plus
`local/` and `pipeline/scratch/` for pipeline output.

## Status and TODO

Done:
- Local pipeline over the NOAA buckets, tested on 24 scans (2025-01-07 18:00 to
  20:00 UTC): append, dedupe, and a read-back that matches the raw netCDF.
- Catalog gates pass on the root catalog.

TODO:
- **Publish to Source Cooperative.** Confirm the account, product name, and write
  endpoint, then fill in the links at the top of this file. The path in
  `catalog.publish.yaml` is a guess based on the FIRMS mirror.
- Build the Palisades window and check the FRP curve against the published
  figure.
- Write the `goes-18/abi-l2-fdcc` collection, validate it, and record accepted
  findings in `docs/conformance.md`.
- Decide the license value for the catalog.
- Hourly update job on GitHub Actions.
- Settle the Kerchunk export so one parquet covers the whole cube.

## License

Code: Apache-2.0, see `LICENSE`. Data: produced by NOAA. A license value for the
catalog is not decided yet. See [docs/architecture.md](docs/architecture.md).
