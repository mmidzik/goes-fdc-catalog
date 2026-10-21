# goes-fdc-catalog

A [Portolan](https://github.com/portolan-sdi/portolan-spec) catalog mirroring
**NOAA GOES-R ABI fire detections** (Fire/Hot Spot Characterization, FDC) as a
**virtual Zarr cube**.

Catalog metadata lives in this repository. The pixel data stays in NOAA's public
`noaa-goes*` buckets on AWS S3, and the catalog holds byte-range references to
it. The catalog relies on that S3 copy as its data source. CI validates every
change to the metadata.

> **Status: demo, built locally. Publishing to Source Cooperative is TODO.**
> The catalog covers two weeks of full-scene GOES-18 CONUS scans, 2025-01-07
> to 2025-01-20 UTC. The same pipeline extends the cube forward or back in
> time. See [Status and TODO](#status-and-todo).

- **Published catalog**: TODO, not on Source Cooperative yet
- **STAC root**: TODO, same
- **Browse it in the Portolan browser**: TODO, needs the published STAC root
- **Upstream**: https://registry.opendata.aws/noaa-goes/ (NOAA and NESDIS
  produce the data and remain the authoritative source)
- **Design**: [docs/architecture.md](docs/architecture.md)

This catalog is a first test of Zarr in a Portolan catalog. Portolan defers a
normative Zarr profile until real Zarr datasets have been tested in catalogs
([portolan-spec#132](https://github.com/portolan-sdi/portolan-spec/issues/132)).
The Zarr assets are outside the Portolan conformance surface.

To see it work, run [examples/palisades-frp.ipynb](examples/palisades-frp.ipynb).
It starts at `catalog/catalog.json` and finds the cube through the collection
metadata. The plot shows fire radiative power over the Palisades burn area.

Start with [docs/architecture.md](docs/architecture.md) for the data access
paths, components, flow, and open questions. The collection's own README and
AGENTS.md (what the data is, how to read it, the traps) are under
`catalog/goes-18/abi-l2-fdcc/`. Everything below is about how this repository
builds that catalog.

## The GOES data today

GOES-R ABI data is public but not cloud-optimized. Level 2 FDC is netCDF4 on the
ABI fixed grid, one file per scan, with no STAC and no COG or Zarr form from
NOAA.

| Satellite | Role | In `noaa-goes*` (FDCC) |
|---|---|---|
| GOES-16 | GOES-East until 2025-04-07, storage since | 2017/144 to 2025/097 |
| GOES-17 | GOES-West until 2023-01-04, storage since | 2018/239 to 2023/010 |
| GOES-18 | GOES-West since 2023-01-04 | 2022/131 to 2026/279 |
| GOES-19 | GOES-East since 2025-04-07 | 2024/291 to 2026/279 |

The bucket ranges are year and day of year, measured on 2026-10-06. The roles
come from the [NOAA OSPO status page](https://www.ospo.noaa.gov/operations/goes/status.html).
FDCF (full disk) and FDCM (mesoscale) have the same end dates as FDCC. FDCM
starts later on GOES-16 and GOES-17 (2021/137).

The FDC cadence depends on the scan sector:

| Product | Sector | Cadence |
|---|---|---|
| `ABI-L2-FDCF` | Full disk | About every 10 minutes |
| `ABI-L2-FDCC` | CONUS or PACUS | About every 5 minutes |
| `ABI-L2-FDCM` | Mesoscale (two sectors, M1 and M2) | About every 1 minute per sector. Observations arrive every 30 seconds if both sectors point at the same area |

This catalog starts with GOES-18 `ABI-L2-FDCC`, so about 5 minutes between
scans, or about 288 per day. In the 24-scan test the scans fell at 5-minute
steps (18:02:35, 18:07:35, 18:12:35 and so on).

Where the data lives:

| Where | What | Access | Notes |
|---|---|---|---|
| AWS S3 `noaa-goes{16,17,18,19}` | All ABI products, netCDF4 | Anonymous, no account. SNS topic `NewGOES{N}Object` announces new files | Keys are `<product>/<YYYY>/<DDD>/<HH>/<file>`. Range requests and CORS work over `https`. **This catalog reads from here.** |
| Google Cloud `gcp-public-data-goes-{16..19}` | Same files | Anonymous | Mirror of the AWS layout |
| Microsoft Planetary Computer | STAC `goes-cmi` (cloud and moisture imagery as COGs) and `goes-glm` | STAC API | FDC is not a STAC collection there. The STAC API lists only `goes-cmi` and `goes-glm` (checked 2026-10-06) |
| Azure `noaa-goes-cogs` (behind Planetary Computer) | FDC as COGs, one file per variable per scan (`Area`, `DQF`, `Mask`, `Power`, `Temp`) | Needs a Planetary Computer SAS token. Anonymous requests return 404 | Partial: GOES-16 2017 to 2021 and part of 2023, GOES-17 2018 to 2021, GOES-18 only 8 days in 2023, GOES-19 none. Not usable as a public source |
| Google Earth Engine | `NOAA/GOES/{16..19}/FDCF` and `FDCC`, plus `MCMIPF` | Earth Engine account | Raster only |
| NOAA CLASS and NCEI | Long-term archive | Free account | Order-based, not cloud-native |
| SSEC NGFS | Terrain-corrected fire-pixel CSV, GeoJSON and KML from ABI scans | <https://bin.ssec.wisc.edu/pub/volcat/fire_csv/> | Experimental. About 6 days stay online |
| NASA FIRMS | Provisional ABI active-fire detections for the US and Canada from GOES-16 and GOES-18, on the web map | Map only | The FIRMS area API lists no GOES source |

No full-archive vector (point or polygon) form of GOES FDC exists in any of
these. That is why this catalog keeps the raster grid and virtualizes it.

## What it publishes

One collection, `goes-18/abi-l2-fdcc`: the CONUS FDC product from GOES-18. Each
scan is a 1500 × 2500 grid on the ABI geostationary fixed grid, about every 5
minutes. Five variables: `Mask`, `DQF`, `Power`, `Temp`, `Area`.

The demo window is two weeks, 2025-01-07 to 2025-01-20 UTC. Every scan is the
full CONUS scene. The window covers the January 2025 Los Angeles fires, which
the example notebook uses. The pipeline appends by time, so the same cube grows to a longer window
without a rebuild. The next step is two years, built on a cloud machine. Names
follow `abi-<level>-<product><sector>` under one sub-catalog per satellite, so
other satellites and sectors can be added as siblings.

The data asset is one Icechunk repository:

| Asset | Reader needs | Notes |
|---|---|---|
| `icechunk` | `icechunk`, `zarr`, `xarray` | Transactional, appendable, detects a changed NOAA file |

It holds manifests, never pixels. Every read fetches chunk byte ranges from
NOAA. The pilot also built Kerchunk references, which the demo drops. They
cannot detect a changed NOAA file, the JSON form costs about 51 KB per scan, and
one parquet for a growing cube is an unsolved export.

The trade-off: the `icechunk` asset is an Icechunk repository (`repo`,
`snapshots/`, `manifests/`, `transactions/`). A generic Zarr client that does
not know Icechunk cannot open it by URL. The reader must also authorize NOAA's
bucket as a virtual chunk container, and no STAC field says so. Whether
Portolan's Zarr profile should describe virtual stores is a question for
[portolan-spec#132](https://github.com/portolan-sdi/portolan-spec/issues/132).
This catalog is a test case for it.

## Design decisions worth knowing

**We rely on the AWS S3 mirror.** Every pixel read is a Range request to
`https://noaa-goes{16,17,18,19}.s3.amazonaws.com`, the NOAA copy listed in the
[AWS Registry of Open Data](https://registry.opendata.aws/noaa-goes/). The
catalog has no copy of its own, so it works only while those objects stay at
those keys and keep their bytes. That has three consequences:
- If NOAA or AWS moves or deletes a file, the reference breaks. The Icechunk repo
  detects a changed file.
- The GOES-16 and GOES-17 buckets stopped growing (2025/097 and 2023/010), so
  their references are stable. GOES-18 and GOES-19 are live and grow every scan.
- Other mirrors of the same files (Google Cloud, Earth Engine, NCEI) are not
  used. Pointing the catalog at one of them means rebuilding the references,
  because the byte-range URLs name the AWS host.

**Virtual, not copied.** GOES FDC is a raster grid per scan with fire as a few
classes among many, so a fire-pixel table would drop the cloud, clear, and
quality pixels that detection validation needs. The cube keeps the full grid and
copies none of it. FIRMS converts to GeoParquet because its source is already a
list of detections. GOES FDC is not.

**No server.** Readers hit static files on Source Cooperative and NOAA's bucket.
The update job (`.github/workflows/update.yml`) is a GitHub Action with a manual
trigger, not a hosted service. It is a draft and has not run. A schedule turns
it into a live mirror. A later event-driven version could subscribe to NOAA's
`NewGOES18Object` SNS topic.

**One grid per cube.** A virtual cube inherits the grid and encoding of the
files it references. NOAA changes these over a satellite's life: the first
GOES-18 FDCC files (2022/131) sit at `-89.5` degrees as `GOES-Test`, and later
files sit at `-137.0`. Each scan gets a signature (projection, axes, chunks,
codecs, dtype, fill value, scaling). A build stops when a scan's signature
differs from the cube's. Earthmover split the GOES-16 archive into groups for
the same reason.

**Zarr outside conformance.** The collection says so. rashid reports no error
for the Zarr assets. `docs/conformance.md` lists the warnings it reports and
records any finding that is accepted.

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
| `pipeline/src/goes_fdc/virtualize.py` | Reads each netCDF header with VirtualiZarr (`HDFParser`), checks each scan's grid and encoding signature, and stacks scans along `time`. |
| `pipeline/src/goes_fdc/store.py` | Opens the Icechunk repo (local path or `s3://`) and appends new time steps. Refuses a cube whose signature differs from the store's. |
| `pipeline/src/goes_fdc/cli.py` | The `goes-fdc build` command. One commit per UTC day. Resumable: scans already in the store are skipped. |
| `pipeline/src/goes_fdc/collection.py` | Writes `collection.json` from facts read from the store. |
| `pipeline/src/goes_fdc/thumbnail.py` | Renders the collection thumbnail from one scan. |
| `tools/publish.py` | Syncs `catalog/` to the bucket. Template-provided; never widened beyond `catalog/`. |
| `tools/upload_data.py` | Uploads staged data files. Template-provided. |

```bash
uv sync
uv run goes-fdc build --start 2025-01-07T00:00 --end 2025-01-21T00:00
```

The bucket listing is the index. NOAA keys are
`ABI-L2-FDCC/<YYYY>/<DDD>/<HH>/<filename>`, and one anonymous list call per hour
prefix returns the scans. A second run with the same window adds nothing. NOAA
needs no credentials, and reads from the public bucket cost nothing. The store
is built in place at `local/publish/goes-18/abi-l2-fdcc/icechunk`, the path
that `tools/upload_data.py` uploads.

Measured on the two-week build from a laptop (2026-10-21):

| Measure | Value |
|---|---|
| Scans | 3,996 over 14 UTC days |
| Build time | 24 minutes, about 2.8 scans per second with 32 threads |
| Time per day of scans | 89 to 113 s of header reads. Listing and committing each take under 1 s |
| Manifests in the tagged snapshot | 13.3 MB in 73 files, about 3.3 KB per scan |
| Repository on disk | 20 MB, history included |
| Raw netCDF referenced | About 226 KB per scan, never downloaded or copied |

A first build without manifest splitting rewrote every manifest on each daily
append, so the repository grew to 100 MB over 14 commits for 13.3 MB of live
manifests. The store now splits manifests along `time` at 288 scans
(`SPLIT_SCANS` in `store.py`), and a daily append writes only its own day. The
rebuilt repository is 20 MB. Earthmover used
manifest splitting for the same reason on GOES-16.

## Working on this repository

Python dependencies use [uv](https://docs.astral.sh/uv/). It creates `.venv` and
installs the locked versions.

Write the collection from the store, then dry-run the uploads:

```bash
uv run python -m goes_fdc.collection \
    --public-base https://data.source.coop/<ACCOUNT>/goes-fdc-catalog
uv run --group viz python -m goes_fdc.thumbnail --time 2025-01-08T06:00 \
    --out catalog/goes-18/abi-l2-fdcc/thumbnail.png
uv run python tools/publish.py          # dry run: catalog metadata and the root self link
uv run python tools/upload_data.py      # dry run: the Icechunk repo
uv run --group examples jupyter nbconvert --to notebook --execute --inplace \
    examples/palisades-frp.ipynb
```

```bash
uv sync
uv run pytest                          # unit tests, no network
uv run python tests/run_all.py         # gates: conformance, links, STAC validity
uv run rashid check catalog --schema   # the validator directly
uv run python tools/publish.py         # dry run
```

Data files never enter git. `.gitignore` blocks the common formats, plus
`local/` for pipeline output and staged data.

## Status and TODO

Done:
- Local pipeline over the NOAA buckets: append, resume, one commit per day, and
  a grid and encoding check on every scan.
- The two-week cube, built locally: 3,996 scans, tagged `demo-2025-01` in the
  Icechunk repository.
- The catalog, with the root, `goes-18`, and the `abi-l2-fdcc` collection with the
  Icechunk asset, thumbnail, README and AGENTS.md at each level.
- `examples/palisades-frp.ipynb`, which reads the cube through the catalog.

TODO:
- **Extend to two years** on a cloud machine. The pipeline is the same. Only
  the window and the machine change.
- **Publish to Source Cooperative.** The target is a personal account. Its name
  is the `<ACCOUNT>` placeholder in `catalog.publish.yaml`, in the collection
  asset hrefs, and in the published READMEs and AGENTS.md files. Set it in all
  of them, regenerate the collection, then fill in the links at the top of this
  file. `tools/publish.py` refuses `--confirm` while the placeholder is set.
  Install the upload dependency with `uv sync --group upload`. Check that Source
  Cooperative supports the conditional writes Icechunk needs. After the upload,
  run `rashid check catalog --schema --data --live --live-base-url <public base>`
  and re-run the notebook against the public catalog.
- Decide the license value for the catalog.
- Run the update workflow once, then decide whether to schedule it.

## Acknowledgements

Earthmover's post
[Cloud-optimizing the GOES-16 archive as Virtual Zarr](https://www.earthmover.io/blog/virtual-zarr/)
(Tom Nicholas, June 2026) is the source of the approach in this repository. The
post makes the GOES-16 archive available as one virtual Zarr store with
VirtualiZarr and Icechunk, and it copies none of the data. This catalog uses the
same method for the GOES FDC product and publishes the result as a Portolan
catalog. Thank you to Tom Nicholas and the Earthmover team.

Thank you also to the NOAA Open Data Dissemination program and the AWS Open
Data program, which keep the GOES files in public buckets that anyone can read.

## License

Code: Apache-2.0, see `LICENSE`. Data: produced by NOAA. A license value for the
catalog is not decided yet. See [docs/architecture.md](docs/architecture.md).
