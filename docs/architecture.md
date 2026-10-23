# Architecture and methods: GOES-18 FDC as a virtual Zarr cube

Status: demo. Scope: GOES-18 `ABI-L2-FDCC`, full CONUS scene, 2025-01-07 to
2025-01-20, built locally. Updated 2026-10-22.

This document describes how the catalog is built and why. What the data means is
in [catalog/README.md](../catalog/README.md). How to run the pipeline is in the
[repository README](../README.md). The pipeline code is in `pipeline/`. The
published catalog is in `catalog/`.

## 1. Summary

The catalog publishes NOAA's GOES-18 ABI Fire/Hot Spot Characterization (FDC) as
a Portolan catalog. Its one data asset is a **virtual Zarr cube** in an Icechunk
repository. The cube holds byte-range references into NOAA's netCDF files in
`noaa-goes18`. We copy no pixel data and run no server. Everything we host is
static files on Source Cooperative (a personal account, name pending).

The method comes from Earthmover's GOES-16 work, described in
[Cloud-optimizing the GOES-16 archive as Virtual Zarr](https://www.earthmover.io/blog/virtual-zarr/).
This design applies it to the FDC product and replaces Arraylake as the
discovery layer with a Portolan catalog.

The catalog is a Zarr test case for
[portolan-spec#132](https://github.com/portolan-sdi/portolan-spec/issues/132),
which defers a normative Zarr profile until real Zarr datasets have been tested
in catalogs. Zarr stays outside Portolan's conformance surface. Section 10
collects what this catalog found.

## 2. Goals and non-goals

Goals:

- Never copy the dataset.
- No always-on server. Readers hit static files only.
- Stay appendable. NOAA adds a GOES-18 CONUS scan about every 5 minutes.
- Lay out the catalog so other GOES-18 FDC sectors can be added as sibling
  collections.

Non-goals for this version:

- COG, GeoParquet or tile derivatives (see section 11).
- Products other than FDC.
- Any claim of Portolan conformance for the Zarr asset.

## 3. Source data

### 3.1 The files

NOAA writes one netCDF4 (HDF5) file per scan. GOES-18 FDCC files are under
`s3://noaa-goes18/ABI-L2-FDCC/<YYYY>/<DDD>/<HH>/`, with names like:

```
OR_ABI-L2-FDCC-M6_G18_s20250080301172_e20250080303545_c20250080304133.nc
```

`M6` is the ABI scan mode. The `s`, `e` and `c` stamps are scan start, scan end
and file creation, as year, day of year, hour, minute, second and tenths of a
second. `pipeline/src/goes_fdc/keys.py` parses this grammar.

Each file holds five pixel variables on a 1500 × 2500 grid, plus per-scan
scalars (`t`, `time_bounds`, view angles, summary counts and statistics). All
five pixel variables use 250 × 250 HDF5 chunks with gzip and shuffle. A file is
about 226 KB. The measured layout of each variable is in the
[collection agent guide](../catalog/abi-l2-fdcc/AGENTS.md), and the code tables
are in [catalog/README.md](../catalog/README.md).

The grid is the ABI geostationary fixed grid. `x` and `y` are scan angles in
radians. The projection is in the `goes_imager_projection` variable: a
geostationary projection with `sweep_angle_axis` `x`, centered at 137.0° W for
the files in this window.

### 3.2 Where the data lives

| Where                                              | What                                                                         | Access                                                                 | Notes                                                                        |
| -------------------------------------------------- | ---------------------------------------------------------------------------- | ---------------------------------------------------------------------- | ---------------------------------------------------------------------------- |
| AWS S3 `noaa-goes18`                               | All GOES-18 ABI products, netCDF4                                            | Anonymous, no account. SNS topic `NewGOES18Object` announces new files | Range requests and CORS work over `https`. **This catalog reads from here.** |
| Google Cloud `gcp-public-data-goes-18`             | Same files                                                                   | Anonymous                                                              | Mirror of the AWS layout                                                     |
| Microsoft Planetary Computer                       | STAC `goes-cmi` (cloud and moisture imagery as COGs) and `goes-glm`          | STAC API                                                               | FDC is not a STAC collection there (checked 2026-10-06)                      |
| Azure `noaa-goes-cogs` (behind Planetary Computer) | FDC as COGs, one file per variable per scan                                  | Needs a Planetary Computer SAS token. Anonymous requests return 404    | Partial: GOES-18 for only 8 days in 2023. Not usable as a public source      |
| Google Earth Engine                                | `NOAA/GOES/18/FDCF` and `FDCC`                                               | Earth Engine account                                                   | Raster only                                                                  |
| NOAA CLASS and NCEI                                | Long-term archive                                                            | Free account                                                           | Order-based, not cloud-native                                                |
| SSEC NGFS                                          | Terrain-corrected fire-pixel CSV, GeoJSON and KML from ABI scans             | <https://bin.ssec.wisc.edu/pub/volcat/fire_csv/>                       | Experimental. About 6 days stay online                                       |
| NASA FIRMS                                         | Provisional ABI active-fire detections for the US and Canada, on the web map | Map only                                                               | The FIRMS area API lists no GOES source                                      |

NOAA publishes no STAC, COG or Zarr form of FDC. No full-archive vector form of
GOES FDC exists in any of these sources.

Measured on 2026-10-06 against `https://noaa-goes18.s3.amazonaws.com`: anonymous
listing works, a Range request returns `206` with `Accept-Ranges: bytes`, and
the CORS rule allows `*` for GET.

### 3.3 Why virtualize

FDC is a raster per scan, and fire is a few codes among 45. A fire-pixel table
would drop the cloud, clear-land, water and block-out pixels that detection
validation needs. A converted copy of the full grid would duplicate NOAA's
archive. A virtual cube keeps the full grid and copies none of it. FIRMS
converts to GeoParquet because its source is already a list of detections. GOES
FDC is not.

The cost of this choice is a dependency on NOAA's bucket. Every pixel read is a
Range request to `https://noaa-goes18.s3.amazonaws.com`. The catalog works only
while those objects stay at those keys with the same bytes. The other mirrors in
3.2 are not used. A switch to one of them means a rebuild of the references,
because each reference names the AWS host.

## 4. Build method

```
 +-------------+   +--------------+   +--------------+   +------------+   +-----------+
 | List scans  |-->| Virtualize   |-->| Append to    |-->| Write STAC |-->| Publish   |
 | keys.py     |   | virtualize.py|   | Icechunk     |   | collection |   | publish.py|
 | obstore     |   | VirtualiZarr |   | store.py     |   | .py        |   | upload_   |
 |             |   | HDFParser    |   |              |   |            |   | data.py   |
 +-------------+   +--------------+   +--------------+   +------------+   +-----------+
```

`goes-fdc build --start ... --end ...` runs the first three steps one UTC day at
a time. It lists, virtualizes and commits a day before it starts the next, so a
long build holds one day in memory, and a stopped build resumes at the next day.

### 4.1 Listing

The bucket listing is the index. There is no separate indexer or database.
`keys.list_scans` makes one anonymous list call per UTC hour prefix, on a thread
pool, with `obstore`. It keeps the keys whose start stamp falls in the window
and sorts them by start time.

Before it lists, the build reads the last `time` value in the store. It skips
days that end before that value and drops listed scans that start before it. A
second run over the same window adds nothing.

### 4.2 Virtualization

`virtualize.virtualize_scan` opens each file with VirtualiZarr's
`open_virtual_dataset` and `HDFParser` over `https`. The parser reads the HDF5
metadata with Range requests and records, for each chunk, the file URL, byte
offset and length. It reads no pixel chunks.

- `t`, `x` and `y` are loaded as values. Everything else stays virtual.
- `decode_times=False`. Some files carry the fill value in `time_bounds`, which
  stops CF time decoding of the whole file. The build decodes `t` alone.
- The cube keeps the five pixel variables and the `time`, `x` and `y`
  coordinates. The per-scan scalars are dropped. An early Kerchunk export failed
  on them (section 12), and a cube has no use for one scalar per scan.
- Each scan gets a `time` dimension of length 1. `xr.concat` stacks the scans of
  a day along `time`.

CF attributes survive virtualization. `scale_factor`, `add_offset` and
`_FillValue` stay on the arrays, so a reader decodes `Temp` and `Area` the same
way as from the netCDF.

### 4.3 The time coordinate

`time` is the file's `t`, which falls mid-scan. For example, a scan that starts
at 18:01:17 has `t` 18:02:35.85. The start stamp in the file name is not used,
because `t` is the value NOAA records for the scan.

A file can carry a fill value in `t` and valid pixels. Decoded, such a `t`
falls far outside the scan, with no error. `virtualize.scan_time` checks `t`
against the scan's own stamps, with one minute of tolerance on each side. A `t`
that is missing or outside that range gets the midpoint of the start and end
stamps, and the build logs a warning.

NOAA's bucket can have gaps where no file exists for a scan. The build adds no
time step for a missing scan, so the spacing along `time` is not always 5
minutes.

### 4.4 The grid and encoding signature

A virtual cube inherits the grid and encoding of the files it references, so
every scan in one cube must share them. NOAA changes these over a satellite's
life. The first GOES-18 FDCC files (2022/131) sit at -89.5° as `GOES-Test`, and
the later ones at -137.0°, with different `x` and `y` axes.

`virtualize.signature` records, for each scan:

- the projection attributes of `goes_imager_projection`
- the first value, last value and length of `x` and `y`
- for each variable: shape, chunk shape, dtype, fill value, codecs,
  `scale_factor`, `add_offset` and units

Every scan in a day must match the first scan of the day. The store keeps the
signature as the group attribute `goes_fdc:signature`, and each append must
match it. A mismatch raises `EncodingMismatch` and names the facts that differ.
Scans with a different signature belong in a separate cube. Earthmover split the
GOES-16 archive into groups for the same reason.

### 4.5 Writing the Icechunk store

`store.append` writes the day's cube with VirtualiZarr's `to_icechunk`. The
first day creates the arrays. Each later day appends along `time`. Each day is
one Icechunk commit, so a failed day commits nothing and the next run retries
it.

The repository configuration sets two things:

- **A virtual chunk container** for `https://noaa-goes18.s3.amazonaws.com/`,
  with `icechunk.http_store()`. The credentials are
  `containers_credentials({url: Credentials.HttpAccess()})`, because the bucket
  is anonymous. Passing `None` is deprecated.
- **Manifest splitting** along `time` at 288 scans (`SPLIT_SCANS`), one day of
  CONUS scans. Without it, each daily append rewrote the whole manifest of each
  array (section 9).

The local store is built in place at `local/publish/abi-l2-fdcc/icechunk`, the
path the asset href names, so `tools/upload_data.py` uploads it unchanged. The
demo snapshot has the tag `demo-2025-01`. Icechunk refuses to create a tag with
the name of a deleted tag, so choose tag names before publishing.

A local filesystem Icechunk repository is not safe for concurrent commits. The
update workflow writes to object storage and allows one run at a time.

### 4.6 Catalog metadata

`goes_fdc.collection` writes `collection.json` from facts read from the store:
the number of scans, the time extent, the grid shape, the `x` and `y` extents,
the variable units, and the projection. It builds the WKT2 from the stored
signature with `pyproj.CRS.from_cf`. The metadata cannot drift from the data,
because the data is its only input. The bbox is NOAA's
`geospatial_lat_lon_extent` for the scene.

`goes_fdc.thumbnail` renders `Power` from one scan. The template's
`tools/publish.py` syncs `catalog/` to the bucket. `tools/upload_data.py`
uploads the store. Its suffix allow-list bars Icechunk's suffixless files, so it
also admits any file under a directory named exactly `icechunk`.

## 5. The Zarr store

The asset is an Icechunk repository: `repo`, `snapshots/`, `manifests/` and
`transactions/`. Each snapshot is a Zarr v3 hierarchy with the cube at the root
group:

| Node                                   | Shape                | Content                                                         |
| -------------------------------------- | -------------------- | --------------------------------------------------------------- |
| `Mask`, `DQF`, `Power`, `Temp`, `Area` | `time` × 1500 × 2500 | Virtual chunks, 1 × 250 × 250, each a byte range in a NOAA file |
| `time`                                 | 3,996                | Native chunks, mid-scan times                                   |
| `x`, `y`                               | 2500, 1500           | Native chunks, scan angles in radians                           |

The root group carries `goes_fdc:signature`. The arrays carry NOAA's CF
attributes. The store has one resolution level and no multiscales.

### 5.1 Reading

A reader needs `icechunk`, `zarr` and `xarray`:

1. Open the repository with `icechunk.http_storage(<asset href>)`.
2. Authorize `https://noaa-goes18.s3.amazonaws.com/` as a virtual chunk
   container with `icechunk.http_store()` and `Credentials.HttpAccess()`.
3. Open a read-only session on the tag `demo-2025-01` or the branch `main`.
4. Call `xr.open_zarr(session.store, consolidated=False)`.

The full recipe is in the
[collection README](../catalog/abi-l2-fdcc/README.md#access). Without step 2,
the open fails with `InvalidInputError` and a message that names the container
to authorize. A generic Zarr client that does not know Icechunk cannot open the
store by URL.

`dask` is optional. `chunks={}` needs it, and a plain read does not.

### 5.2 Change detection

VirtualiZarr stamps each virtual reference with the time it was written.
Icechunk sends that time in `If-Unmodified-Since` on every chunk read. NOAA's
bucket answers `412` for a file modified after that time, and Icechunk stops
with `the checksum of the object owning the virtual chunk has changed`. The
check is by time, not by content. A re-upload of identical bytes also stops the
read.

The check works only against a server that honors the header. Against a server
that ignores it, a newer file reads without error, and a replaced file fails
only in decompression (section 9).

`noaa-goes18` is live and grows with every scan. Existing files can still change
if NOAA reprocesses them, and this check catches that.

## 6. Catalog metadata

### 6.1 Layout

```
catalog/                          root catalog, GOES-18 FDC
  catalog.json  README.md  AGENTS.md
  abi-l2-fdcc/                    collection
    collection.json
    README.md  AGENTS.md  thumbnail.png
    (icechunk/ on Source Cooperative only)
```

- The catalog holds GOES-18 only, so the root catalog holds the collection
  directly. An earlier layout had a `goes-18` sub-catalog, which repeated the
  same facts in one more README and AGENTS.md. The demo dropped it.
- Collection id rule: `abi-<level>-<product><sector>`, lowercase. Later siblings
  could be `abi-l2-fdcf`, and `abi-l2-fdcm1` and `abi-l2-fdcm2`.
- No items. The cube is the access path, and the spec allows a collection with
  assets and no items. About 288 scans per day makes static per-scan items
  heavy.
- No empty collections for products not yet built.
- Mirror fields: a `via` link to the AWS registry page, a top-level `updated`,
  NOAA NESDIS as `producer` and `licensor`, and the host last.

### 6.2 Zarr and datacube fields

| Field                                                     | Value                                                      | Why                                                                         |
| --------------------------------------------------------- | ---------------------------------------------------------- | --------------------------------------------------------------------------- |
| Asset `type`                                              | `application/vnd+zarr`                                     | The media type says Zarr. It cannot say Icechunk (section 10)               |
| `zarr:zarr_format`, `zarr:node_type`, `zarr:consolidated` | `3`, `group`, `false`                                      | Icechunk stores have no consolidated metadata                               |
| `xarray:open_kwargs`                                      | `{"engine": "zarr", "consolidated": false}`                | A client knows how to call `open_zarr` without a guess                      |
| `proj:code`                                               | `null`                                                     | A geostationary grid has no EPSG code                                       |
| `proj:wkt2`, `proj:shape`                                 | WKT2 of `goes_imager_projection`, `[1500, 2500]`           | Enough to convert a longitude and latitude box to scan angles with `pyproj` |
| `cube:dimensions`                                         | `time`, `y`, `x`, with `y` and `x` in `rad`                | Describes the cube axes                                                     |
| `cube:variables`                                          | The five variables with units                              |                                                                             |
| `renders`                                                 | `frp`: `Power` on `inferno`, rescale 0 to 200, nodata `-9` | Display hints in place of statistics                                        |

The collection declares the `zarr` v1.1.0, `xarray-assets` v1.0.0, `datacube`
v2.2.0, `projection` v2.0.0, `render` v2.0.0 and `file` v2.1.0 extensions.
Portolan pins the render extension at v2.0.0, so the collection uses v2.0.0 and
not v2.1.0.

The collection carries no computed statistics. A growing cube's statistics
change on every append. The `render` hints carry what a viewer needs instead.

## 7. Data access paths

| Path          | What the reader needs                                                                   | What it reads                                                              |
| ------------- | --------------------------------------------------------------------------------------- | -------------------------------------------------------------------------- |
| A. Browse     | A STAC client or the Portolan browser                                                   | `catalog.json`, `collection.json`, README, AGENTS.md on Source Cooperative |
| B. Icechunk   | `icechunk`, `zarr`, `xarray`. Anonymous reads of Source Cooperative and the NOAA prefix | Manifests on Source Cooperative, then chunk byte ranges from NOAA          |
| C. Raw netCDF | Anything that reads netCDF                                                              | NOAA's files directly. The catalog has no per-scan asset for them          |

Data bytes always come from NOAA. We host only manifests and metadata.

A reader can also list a short window and virtualize it on the fly with no
store. That costs a few header requests per file, about 288 files per day. The
store caches that work, so a long window opens without the header reads.

## 8. Updates and operations

| On Source Cooperative (static files)                   | On compute we run                                |
| ------------------------------------------------------ | ------------------------------------------------ |
| Icechunk repo, STAC JSON, README, AGENTS.md, thumbnail | The append job on GitHub Actions                 |
|                                                        | One-off backfills on a laptop or a cloud machine |

`.github/workflows/update.yml` appends a time window to the published store,
regenerates the collection, and publishes the metadata. It is a draft with a
manual trigger and has not run. It:

- appends in place to the store on Source Cooperative. It does not stage a copy
  and sync it, because a partial sync of an Icechunk repo can leave refs that
  point at snapshots that are not uploaded yet.
- runs one job at a time (`concurrency: update-store`), because Icechunk takes
  one writer per commit.
- reads Source Cooperative credentials from a GitHub environment secret.

Not yet verified: that Source Cooperative supports the conditional writes
Icechunk needs to commit, and its CORS and Range behavior for the store.

A schedule turns the workflow into a live mirror. A later event-driven version
could subscribe a queue to NOAA's `NewGOES18Object` SNS topic. Each message
carries the new key, so no listing is needed. One consumer would batch messages
into one commit, since a store has one writer per commit. The hourly list job
would stay as a reconciler, because SNS delivery is not guaranteed. The
virtualize and append code is the same in both models.

## 9. Verification and measurements

Tool versions: VirtualiZarr 2.7.3, Icechunk 2.3.0, zarr 3.4.0, xarray 2026.9.0.

### 9.1 Correctness

- **Read-back.** All five variables of three sampled scans are byte-identical to the raw netCDF. An earlier 24-scan build
  matched for four sampled scans.
- **Decoded values.** Decoded `Temp` runs 400 to 2693 K over 24 scans.
- **Append.** Two runs over 2025-01-07 18:00 to 20:00 UTC added 12 scans each,
  and a third run added 0. The time axis stays unique and monotonic.
- **HTTP read from a clean environment.** A fresh environment with only
  `icechunk`, `zarr` and `xarray` opened the store through
  `icechunk.http_storage`, served from `local/publish` by a local HTTP server.
  It found the tag `demo-2025-01` and 3,996 scans.
  The fire radiative power over the Palisades box (118.70 W to 118.45 W, 34.00 N
  to 34.15 N) at 2025-01-08T07:12Z was 26,255 MW, the same as a local read.
- **Change detection.** NOAA's bucket answered `412` to a request with an
  `If-Unmodified-Since` date before the file's `Last-Modified`, and `206` with a
  later date. A store pointed at a local copy of a NOAA file was read three
  times. With a server that ignores the header, a newer modification time read
  without error, and a replaced file failed only in decompression. With a server
  that answers `412` as S3 does, both cases stopped the read.
- **Validation.** `rashid check catalog --schema` reports 0 errors. The warnings
  are in [conformance.md](conformance.md).

### 9.2 The two-week build

Measured from an empty store on a laptop with 32 threads (2026-10-21):

| Measure                          | Value                                                                   |
| -------------------------------- | ----------------------------------------------------------------------- |
| Scans                            | 3,996 over 14 UTC days                                                  |
| Build time                       | 24 minutes, about 2.8 scans per second                                  |
| Time per day of scans            | 89 to 113 s of header reads. Listing and committing each take under 1 s |
| Manifests in the tagged snapshot | 13.3 MB in 73 files, about 3.3 KB per scan                              |
| Repository on disk               | 20 MB, history included                                                 |
| Raw netCDF referenced            | About 226 KB per scan, never downloaded or copied                       |
| Thumbnail                        | 9.6 KB PNG                                                              |

A first build without manifest splitting rewrote every manifest on each daily
append. After 14 daily commits that repository held 100 MB for 13.3 MB of live
manifests, so it grew with the square of the number of commits. With splitting
along `time` at 288 scans, four 24-scan appends wrote 78 to 81 KB each, and the
rebuilt repository is 20 MB. Earthmover used manifest splitting for the same
reason on GOES-16.

### 9.3 Read cost

`examples/palisades-frp.ipynb` reads `Power` and `Mask` over a 6 × 9 pixel box
for all 3,996 scans in 103 to 109 s. That is one chunk per variable per scan,
7,992 Range requests to NOAA, from the local manifests.

### 9.4 Serving the store locally

Icechunk sends its first requests in parallel. Python's single-threaded
`RangeHTTPServer` dropped the request for `repo`, and Icechunk reported
`RepositoryNotFoundError`. A threaded server worked. A local preview of the
store needs a threaded server with Range support.

## 10. Zarr in Portolan: findings from this demo

Portolan defers a normative Zarr profile until real Zarr datasets have been
tested in catalogs
([portolan-spec#132](https://github.com/portolan-sdi/portolan-spec/issues/132)).
This section collects what this catalog found as one of those tests. Each item
is marked **measured** (observed in this repository) or **open** (a question for
the spec).

### 10.1 Gaps in the catalog metadata

- **The virtual chunk container (measured).** The cube's chunks live in NOAA's
  bucket, not next to the store. Icechunk reads them only after the reader
  authorizes `https://noaa-goes18.s3.amazonaws.com/` as a virtual chunk
  container. No field in the STAC `zarr` or `xarray` extensions carries that.
  Today the recipe is in the collection README, and
  `examples/palisades-frp.ipynb` copies it by hand.
- **That the store is Icechunk (measured).** The asset media type is
  `application/vnd+zarr`. It says Zarr, not Icechunk. A generic Zarr client
  cannot open the repository by URL, and the media type does not tell a client
  that it needs the `icechunk` library.
- **How to build the storage (measured).** The href gives a location. The reader
  still picks local, `http`, or `s3` storage from the href scheme.
- **Which snapshot to open (open).** An Icechunk repository has branches and
  tags, and this catalog publishes the whole repository. The tag `demo-2025-01`
  appears in the collection README, but in no metadata field.
- **Which grid era a cube covers (open).** A virtual cube inherits the grid of
  the files it references. GOES-18 FDCC changed its projection origin in 2022,
  so one satellite needs more than one cube to cover its whole record. No field
  states the era of a cube or links the cube for another era.
- **Checksum and size of a directory asset (measured).** The `icechunk` asset is
  a directory, so it has no one `file:checksum` or `file:size` value. rashid
  0.1.8 reports PTL-AST-003 as a warning for each.

### 10.2 What worked

- **Discovery (measured).** pystac walked root, the former `goes-18`
  sub-catalog, and `abi-l2-fdcc` with no special handling. The flat layout has
  one level less and is not re-run yet. The asset gives the href, media type,
  and `xarray:open_kwargs`, and that is enough to call `xarray.open_zarr` once
  the store is open.
- **Projection (measured).** `proj:wkt2` on the asset is enough to convert a
  longitude and latitude box to fixed-grid scan angles with `pyproj` alone. The
  notebook needs no GOES-specific code for that step.
- **Validation (measured).** rashid reports 0 errors on the catalog. Zarr stays
  outside the conformance surface, and the README says so.

### 10.3 Lessons from building and serving a virtual store

- **Split manifests from the start (measured).** Without manifest splitting, the
  repository grew with the square of the number of commits (section 9.2).
- **An archive is not one grid (measured).** The first GOES-18 FDCC files sit at
  -89.5° and later files at -137.0°, with different `x` and `y` axes. The
  pipeline compares a signature of each scan against the cube and stops on a
  mismatch.
- **Bad headers become bad coordinates (measured).** A file can carry a fill
  value in `t` with valid pixels, and it decodes to a wrong time without an
  error. A virtual cube copies header values, so a header check belongs in the
  build.
- **Tags are permanent (measured).** Icechunk refuses to create a tag with the
  name of a deleted tag. Choose published tag names before the first upload.
- **Change detection depends on the source server (measured).** Icechunk detects
  a changed source file only when the server honors `If-Unmodified-Since`.
  NOAA's S3 bucket does. A virtual store over a plain HTTP mirror that ignores
  the header gets no protection.
- **Cost (measured).** The build reads headers only, about 2.8 scans per second
  from a laptop, and writes about 3.3 KB of manifest per scan. A read of a small
  box touches one chunk per variable per scan.

## 11. Open questions and later work

| #   | Question                                                                          | Status                                                                                                                                                        |
| --- | --------------------------------------------------------------------------------- | ------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| 1   | Is FDC virtualizable?                                                             | **Settled 2026-10-06: yes.** Section 9.1                                                                                                                      |
| 2   | Can the catalog state a geostationary CRS?                                        | **Settled for STAC: `proj:wkt2` with `proj:code` null.** Section 10.2. The Zarr `proj` and `spatial` conventions are not used in the store and are not tested |
| 3   | Can the virtual chunk container read NOAA over `https`?                           | **Settled: yes, with `http_store()` and `HttpAccess`.** Section 4.5                                                                                           |
| 4   | What does the Portolan validator do with a Zarr asset?                            | **Settled: 0 errors, PTL-AST-003 warnings.** Section 10.1                                                                                                     |
| 5   | License value                                                                     | **Settled: `CC0-1.0`.** NOAA's Open Data Dissemination program releases its data under CC0-1.0. See the [catalog README](../catalog/README.md#license)        |
| 6   | Does Source Cooperative support conditional writes, CORS and Range for the store? | Open. Check before the first upload                                                                                                                           |
| 7   | How to re-sync after NOAA reprocesses a file                                      | Open. Icechunk detects the change. A re-sync rule is not defined                                                                                              |
| 8   | How to point the catalog back at this repository                                  | Open, as in the template ([portolan-spec#145](https://github.com/portolan-sdi/portolan-spec/issues/145))                                                      |

Later, not in this version:

- **Two years of scans** on a cloud machine with the same `goes-fdc build`
  command. Measure manifest size and open time.
- **Other GOES-18 sectors** (full disk `FDCF`, mesoscale `FDCM`) as sibling
  collections, one cube per grid.
- **An on-request COG endpoint.** A small stateless function renders one scan
  from the references, behind a CDN. Only if a raster-file consumer needs it. It
  would be the first part of this design with real infrastructure.
- **A fire-pixel GeoParquet** in the FIRMS style, as a conformant vector view.
- **An NGFS mirror.** Upstream keeps about 6 days online.
- **A small client library** in the style of `aef-loader`: key index, virtual
  reader, grouping by sector.

## 12. History

- **Stage 1, 24-scan pilot (2026-10-06).** GOES-18 FDCC, 2025-01-07 18:00 to
  20:00 UTC. Settled questions 1 and 3. The pilot built both an Icechunk repo
  (248 KB, manifests 156 KB) and Kerchunk references. The smoke-test catalog was
  30 files and 1.4 MB, with 56 KB of catalog metadata.
- **Kerchunk dropped.** The Kerchunk JSON cost about 51 KB per scan (1.2 MB for
  24 scans). Parquet was about 4 KB per scan, but it needs a `.zmetadata`
  dotfile that the template's upload gate bars, and one parquet file for a
  growing cube is an unsolved export. The parquet export also raised
  `KeyError: 'local_zenith_angle/.zarray'` until the cube kept only `time`, `x`
  and `y`. Kerchunk references cannot detect a changed source file. The Kerchunk
  reader worked with `engine="kerchunk"` and
  `storage_options={"remote_protocol": "https"}`, and failed with the `zarr`
  engine and `reference://`.
- **Stage 1b, two-week demo (2026-10-21).** 2025-01-07 to 2025-01-20, which
  covers the January 2025 Los Angeles fires. Added the signature check, the `t`
  rule, one commit per UTC day, manifest splitting, the example notebook, and
  the draft update workflow.
- **Stage 2, next.** Extend to two years, publish to Source Cooperative, run the
  update workflow once, and report findings on #132.

The repository was created from
[portolan-catalog-template](https://github.com/portolan-sdi/portolan-catalog-template).
It keeps the publish boundary, `tools/publish.py`, `tools/upload_data.py`, the
CI gates (`test_stac_valid.py`, `test_links.py`, `test_conformance.py`), and
`docs/conformance.md`. It adds `pipeline/` and the update workflow.
