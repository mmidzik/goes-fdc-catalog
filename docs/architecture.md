# Architecture: GOES ABI FDC as a virtual Zarr Portolan catalog

Status: demo. Scope: GOES-18 `ABI-L2-FDCC`, 2025-01-07 to 2025-01-21 (the Palisades fire), built locally. The pipeline extends the window. Updated 2026-10-21.

The pipeline code is in `pipeline/`. The published catalog is in `catalog/`.

## 1. Summary

Publish NOAA's GOES ABI Fire/Hot Spot Characterization (FDC) as a Portolan catalog whose main asset is a **virtual Zarr cube**. The cube holds byte-range references into NOAA's raw netCDF in `s3://noaa-goes18`. We copy no pixel data and run no server. Everything we host is static files on Source Coop (a personal account, name pending).

The approach comes from Earthmover's GOES-16 virtual Zarr work, described in [Cloud-optimizing the GOES-16 archive as Virtual Zarr](https://www.earthmover.io/blog/virtual-zarr/). This design applies it to FDC, and replaces Arraylake as the discovery layer with a Portolan catalog on Source Coop.

This catalog is a Zarr reference implementation for [portolan-spec #132](https://github.com/portolan-sdi/portolan-spec/issues/132), which defers a normative Zarr profile until real Zarr datasets have been tested in catalogs. Zarr stays outside Portolan's conformance surface, and the README says so.

## 2. Goals and non-goals

Goals:
- Never copy the full dataset.
- No always-on server. Readers hit static files only.
- Stay appendable: new scans land every 5 minutes.
- Design the layout so more satellites, sectors and products slot in later.

Non-goals for v1:
- COG, GeoParquet or tile derivatives (possible later, see section 9).
- Non-fire pixel analysis products.
- Any claim of Portolan conformance for the Zarr assets.

## 3. Data access

How a user reads GOES FDC through this catalog:

| Path | What the reader needs | What it reads |
|---|---|---|
| A. Browse | A STAC client or the Portolan browser | `catalog.json`, `collection.json`, README, AGENTS.md on Source Coop |
| B. Icechunk (primary) | `icechunk`, `zarr`, `xarray`. Anonymous read of Source Coop plus the NOAA prefix | Repo manifests on Source Coop, then chunk byte ranges from NOAA netCDF |
| C. Raw | Anything that reads netCDF | `source`-role asset (`https` href, `s3` alternate) per scan |

Notes:
- Data bytes always come from NOAA. We host only manifests and metadata.
- Both Zarr assets carry `xarray:open_kwargs`, so a client knows the engine and consolidation without guessing.
- `https` is the primary href form (spec). `s3://` goes in alternate-assets.
- Checked 2026-10-06: `https://noaa-goes18.s3.amazonaws.com/...` answers Range requests with 206 and allows CORS `*` for GET. Anonymous listing works.
- If NOAA rewrites or removes a file, Icechunk's virtual chunk checks catch the change.
- The pilot also built Kerchunk references (path C in an earlier draft). The demo drops them. They cannot detect a changed file. The JSON form costs about 51 KB per scan, and one parquet for a growing cube is an unsolved export. See section 12.

## 4. Components and compute

```
 +--------------+   +--------------+   +-----------+   +-----------+
 | Virtualizer  |-->| Store writer |-->| Catalog   |-->| Publisher |
 | list + open  |   | Icechunk +   |   | builder   |   | sync to   |
 | VirtualiZarr |   | (append,     |   | STAC/docs |   | Source    |
 | HDFParser    |   +--------------+   +-----------+   | Coop      |
 +--------------+                                      +-----------+
      ^
      '-- scheduler: GitHub Actions cron (no hosted service)
```

There is no separate indexer. The bucket listing is the index: one anonymous list call per hour prefix returns the keys, and the job lists only prefixes after the store's last `time`. A reader can also list a short window and virtualize it on the fly with no store (fine for a day or a week, about 288 files per day with a few header requests each). The stored refs cache that work so the archive opens without years of header reads.

| Component | Job | Tool |
|---|---|---|
| Virtualizer | List new keys under `ABI-L2-FDCC/<YYYY>/<DDD>/<HH>/` since the store's last `time` (`obstore`, anonymous), parse filenames (scan mode, `s`/`e`/`c` stamps), open each netCDF as a virtual dataset (header range reads, no pixel reads), concatenate along `time` | **VirtualiZarr** (`open_virtual_dataset`, `HDFParser`), `obstore` |
| Store writer | Check each scan's grid and encoding signature against the store. Append the new time steps as one transaction per UTC day | **Icechunk** (`to_icechunk`) |
| Catalog builder | Write `catalog.json`, `collection.json`, items if any, `README.md`, `AGENTS.md`, thumbnail, `render` hints, `updated` | `portolan` CLI where it supports this, otherwise a script |
| Publisher | Upload the Icechunk repo, parquet refs and STAC files | S3-compatible sync to Source Coop |
| Scheduler | Hourly cron | GitHub Actions |

Hosting split:

| On Source Coop (static files) | On compute we own |
|---|---|
| Icechunk repo, STAC JSON, README, AGENTS.md, thumbnail | The append job (list, virtualize, commit, upload) on GitHub Actions |
| | One-off backfill run on a laptop or larger runner |

- Nothing is always on. The Icechunk repo holds the state (last `time`), so there is no database.
- Source Coop write credentials live in a GitHub secret.
- Only the later COG endpoint (section 9) would add real infra: a Lambda function behind a CDN.
- To verify in the pilot: Icechunk commits need conditional writes on the object store, so confirm Source Coop supports that for a writable repo. Also confirm Source Coop's CORS and Range behavior for the Zarr assets.

Compute budget (to be measured in the pilot):
- Incremental: about 12 new scans per hour. Header reads only. Seconds to a minute on a standard runner.
- Backfill: GOES-18 FDCC since 2023-01-04 is on the order of 400k files. Header-only, so parallelize with a thread pool or Dask. Plan for hours on one machine. Run once, locally or on a larger runner.
- Peak memory is small because no pixel data loads.

Use VirtualiZarr for everything about references: parsing, combining, the manifest model, writing Icechunk. Custom code covers only listing, naming, STAC writing and publishing.

## 5. Flow

Backfill (once):
1. Virtualizer lists all FDCC keys for the period.
2. It builds virtual datasets in batches (for example one day per batch).
3. Store writer commits each batch to the Icechunk repo. Pilot day first.
4. Catalog builder writes metadata. Publisher uploads.

Incremental (hourly):
1. Virtualizer lists the last few hours and diffs against the store's last `time` value.
2. It opens only new files.
3. Store writer appends to the **level-0 group** (not the store root). One commit per run.
4. Update `updated` in the root catalog and collection. Publisher syncs changed files.

Failure handling: a failed run commits nothing, since Icechunk commits are transactional. The next run recomputes the diff.

Trigger model: v1 is pull-based (hourly cron, data lands up to an hour late). A later event-driven version subscribes a queue to NOAA's `NewGOES18Object` SNS topic. Each message carries the new key, so no listing is needed. A single consumer batches messages (every few minutes) into one Icechunk commit, since a store has one writer per commit. Keep the hourly list job as a reconciler because SNS delivery is not guaranteed. The virtualize and append code is the same in both models. The event-driven version is the first part of this design that needs always-available cloud pieces (subscription, queue, small function), so it follows the pilot.

## 6. Catalog layout

```
goes-fdc/                       root catalog, mirror of NOAA GOES-R ABI FDC
  README.md  AGENTS.md          states the naming rule and planned siblings
  goes-18/                      sub-catalog per satellite (slot and dates in README)
    abi-l2-fdcc/                collection
      collection.json           providers, license, `via`, `updated`, datacube dims
      README.md  AGENTS.md
      assets: icechunk (zarr), thumbnail
```

- Per-satellite sub-catalogs avoid the East and West handoffs (GOES-17 to 18 on 2023-01-04, GOES-16 to 19 on 2025-04-07).
- Collection id rule: `abi-<level>-<product><sector>`, lowercase. Later siblings: `goes-16 17 19`, `abi-l2-fdcf`, `abi-l2-fdcm1` and `fdcm2` (mesoscale sectors move), then CMIP and Rad.
- Items: the cube is the main access path, and the spec allows single-asset collections without items. About 288 scans per day makes static items heavy. Add per-scan items only if a use case needs them (they would carry the `source` netCDF asset).
- Do not create empty collections for products not yet built.
- Mirror fields: `via` link to the AWS registry page, top-level `updated`, `producer` NOAA/NESDIS, `host` provider last with contact.

## 6a. Repo: seed from portolan-catalog-template

The repo was created from [portolan-sdi/portolan-catalog-template](https://github.com/portolan-sdi/portolan-catalog-template). The org governance workflows were removed.

Kept as is:
- `catalog/` is the published tree. STAC JSON, README, AGENTS.md and thumbnail live there. Nothing outside it publishes.
- `tools/publish.py` and `tools/upload_data.py` (dry run by default). Data stays out of git and is referenced by URL.
- CI gates: `test_stac_valid.py` (`stac-check`), `test_links.py`, `test_conformance.py` (`rashid`).
- `docs/conformance.md` records accepted validator findings. Expect Zarr assets to trip `rashid`, so record each finding and the reason (Zarr is outside conformance per #132).
- Agent norms, writing hook, Vale.

Added:
- `pipeline/` outside `catalog/`: the VirtualiZarr job (list, virtualize, check, append) and its tests.
- Extend the `upload_data.py` allow-list to admit the Icechunk repo, whose files have no suffix.
- Stage 2: the job writes the Icechunk repo straight to Source Coop. Do not stage and sync it, because a partial upload can break commit atomicity. STAC goes through the template tools. `goes-fdc build --store s3://...` appends in place.
- One GitHub Actions workflow for the hourly job.
- Leave "how the catalog points back at this repo" undecided, as the template does (portolan-spec#145).

## 7. Zarr metadata decisions

Follows the provisional direction in #132:
- Zarr v3 with the `multiscales`, `spatial` and `proj` conventions. One level only. No minimum pyramid depth.
- STAC extensions: `zarr`, `datacube`, `projection`, `cf`, `render`.
- Asset fields: `zarr:node_type`, `zarr:zarr_format`, `xarray:open_kwargs`.
- No computed statistics. A growing cube's stats change on every append. Use `render` hints (`rescale`, `colormap_name`, `nodata`).
- CRS: the ABI fixed grid, so `proj` carries WKT2 or PROJJSON from `goes_imager_projection` (`sweep_angle_axis=x`), not an EPSG code.
- Variables: `Mask`, `DQF`, `Power`, `Temp`, `Area`. Keep raw codes (fire 10 to 15 and 30 to 35, saturation 11 and 123, high zenith 50).
- Time: stack scans along `time` on the single 1500 x 2500 CONUS grid. Record scan start and end per step. Mode changes (M3, M4, M6) change cadence, not grid.

## 8. Risks and open questions

| # | Question | How to settle |
|---|---|---|
| 1 | Is FDC virtualizable? HDF5 chunking, deflate codec, CF `scale_factor` / `add_offset` / `_FillValue`, shared grid across variables, a usable time coordinate (`t`) | **Settled 2026-10-06: yes.** See section 12 |
| 2 | Does the `proj` convention accept a geostationary WKT2 or PROJJSON? Do `spatial` bounds make sense in scan-angle units? | Read the convention, test in pilot, file a spec issue if not |
| 3 | Icechunk virtual chunk container: can it read NOAA over `https`, or only `s3://noaa-goes18/` anonymously? | Pilot |
| 4 | What do the Portolan validator, browser and CLI do with a Zarr asset today? | Read reference catalog, run `portolan --help`, report findings on #132 |
| 5 | License value. No clean SPDX id for US-government public domain | `other` with a NOAA policy link, or `CC0-1.0`. Ask the Portolan team |
| 6 | Thumbnail and style. Raster styling is still open in incubating | Use `render` hints and a static thumbnail first |
| 7 | NOAA reprocessing or file replacement | Icechunk detects changes. Define a re-sync rule |
| 8 | Backfill cost is a guess | Measure on one day, then extrapolate |

## 9. Later, not in this document

- On-request COG endpoint: a small stateless function renders one scan from the refs, CDN cached. Only if a raster-file consumer needs it.
- Fire-pixel GeoParquet (FIRMS style) as the conformant vector view. No existing vector FDC archive was found. FIRMS shows GOES hotspots on its map but the area API lists no GOES source.
- NGFS mirror. Upstream keeps about 6 days online.
- A small client library in the style of `aef-loader`: key index, virtual reader, grouping by satellite and sector. aef-loader itself reads COG to VirtualiZarr, so it supplies the pattern and not the code.
- Not usable: Azure `noaa-goes-cogs` FDC COGs. They need a Planetary Computer SAS token and cover GOES-18 for only 8 days in 2023.

## 10. Rollout

**Stage 1: local, Palisades fire window (no cloud resources).** Window: GOES-18 FDCC, 2025-01-07 to 2025-01-31 UTC (ignition about 18:10Z on 2025-01-07, containment around 2025-01-31, verify the end date). First pass is 2025-01-07 to 2025-01-09 (about 860 scans) to prove the pipeline, then widen to the full window (about 7,200 scans). The collection's temporal extent is the window for now and grows into the full catalog in stage 2.
1. Read the reference catalog, #132, #128, the STAC `zarr` extension, and `portolan --help`.
2. Create the repo from `portolan-catalog-template`. Add `pipeline/` (`uv`, VirtualiZarr, Icechunk, obstore, xarray). Stage 1 writes the Icechunk repo to a gitignored local directory, and STAC files into `catalog/`.
3. List and virtualize GOES-18 FDCC for the first-pass dates from the public bucket. Concatenate along `time`. Commit to a local Icechunk repo. Settle open questions 1 to 3 (virtualizability, `proj`, virtual chunk access).
4. Verify: read back through both paths and compare `Power`, `Mask`, `DQF`, `Temp`, `Area` against a direct netCDF read for sampled scans. Confirm the store holds no pixel bytes.
5. Test the append: add the next days to the existing store and confirm they land in the level-0 group and the store still opens. Time the run to size the cron job and the backfill.
6. Generate the catalog locally (root, `goes-18`, `abi-l2-fdcc`, README, AGENTS.md, thumbnail, `render` hints). Run `portolan` structural and metadata validation. Record what the validator and browser do with the Zarr assets.

Gate: stage 2 starts only when stage 1 passes. Report findings on #132.

**Stage 1b: the two-week demo (done locally, 2026-10-21).** Two weeks over the Palisades fire, 2025-01-07 to 2025-01-21. Kerchunk dropped. A grid and encoding signature check on every scan. One commit per UTC day. `examples/palisades-frp.ipynb` reads the cube through the catalog. The update workflow is drafted with a manual trigger and has not run.

**Stage 2: two years, then publish.**
7. Extend the window to two years on a cloud machine, with the same `goes-fdc build` command. Measure manifest size and open time, and decide on Icechunk manifest splitting from those numbers.
8. Move the store and catalog to the personal Source Coop account. Confirm conditional writes, CORS and Range behavior.
9. Run the update workflow once. Decide whether to schedule it.
10. A human submits the portolan-registry PR and reports findings on #132.

**Later:** SNS trigger, other satellites and sectors, optional COG endpoint and GeoParquet view.

## 11. Verification

- Stage 1: open the local store through paths B and C and read the same scan. Values match a direct netCDF read.
- Stage 2: from a clean environment with no credentials, open the published store through paths B and C.
- Store size is KB to MB per day, with no pixel bytes copied.
- Append a second day. It lands in the level-0 group and the store still opens.
- Every catalog link resolves. Sampled `https` hrefs answer Range requests with 206.

## 12. Stage 1 findings

Measured on 2026-10-06 against `noaa-goes18`, with VirtualiZarr 2.7.3, Icechunk 2.3.0 and zarr 3.4.0.

- **Virtualizable.** All five variables use 250 x 250 chunks with gzip and shuffle. `HDFParser` reads them. Read back through Icechunk, `Mask`, `DQF`, `Power`, `Temp` and `Area` are byte-identical to the raw netCDF for 4 sampled scans.
- **CF scaling survives.** `scale_factor`, `add_offset` and `_FillValue` stay on the arrays. Decoded `Temp` runs 400 to 2693 K over 24 scans.
- **Append works.** Two runs over 2025-01-07 18:00 to 20:00 UTC added 12 scans each, and a third run added 0. The time axis stays unique and monotonic. 24 scans took 248 KB of Icechunk repo and 96 KB of Kerchunk parquet.
- **Time axis.** `time` comes from the file's `t`. It falls mid-scan, for example 18:02:35.85 for a scan that starts 18:01:17.
- **Kerchunk parquet fails on scalar coordinates.** The export raised `KeyError: 'local_zenith_angle/.zarray'` until the cube kept only `time`, `x` and `y`. The pipeline drops the others.
- **Icechunk credentials.** Passing `None` for the HTTP container is deprecated. The pipeline uses `containers_credentials({url: Credentials.HttpAccess()})`.
- **Local filesystem Icechunk is not safe for concurrent commits.** Fine for stage 1. Stage 2 writes to object storage.

Gaps:
- The Kerchunk export covers one batch per run. A single parquet for the whole cube needs either a re-virtualization of everything or a way to derive references from the Icechunk store. Settle this before stage 2.
- Not yet checked: the `proj` convention with a geostationary CRS (question 2), `https` as the virtual chunk container (answered yes for reading: the pipeline reads NOAA over `https`), and what the Portolan validator does with a Zarr asset (question 4).

### Initial smoke-test catalog (2026-10-06)

Built from the 24-scan store, with `goes_fdc.collection` writing the metadata from the store itself.

- **Staged size.** 30 files, 1.4 MB: Icechunk repo 248 KB (manifests 156 KB), Kerchunk JSON 1.2 MB. The catalog metadata is 56 KB.
- **Kerchunk JSON does not scale.** 1.2 MB for 24 scans is about 51 KB per scan. Kerchunk parquet was about 4 KB per scan. The initial catalog uses JSON because the cube is tiny and parquet needs a `.zmetadata` dotfile, which the template's upload gate bars. The full catalog needs parquet.
- **Readers.** `icechunk.http_storage(<https url>)` opens the repo over plain HTTP with Range requests. The NOAA prefix still needs `VirtualChunkContainer(https://noaa-goes18.s3.amazonaws.com/, http_store())` and `Credentials.HttpAccess()`.
- **Kerchunk reader.** `xr.open_dataset(refs_url, engine="kerchunk", storage_options={"remote_protocol": "https"})` works and returns the same `Power` array as Icechunk. The `zarr` engine with `reference://` fails: "Reference-FS's target filesystem must have same value of asynchronous". Needs `kerchunk`, `fsspec`, `aiohttp`, `requests`.
- **Upload gate.** The template's suffix allow-list bars Icechunk's suffixless files. `tools/upload_data.py` now also admits any file under a directory named `icechunk` or `kerchunk`.
- **Validation.** `rashid check catalog --schema`: 0 errors. Warnings: no `file:checksum` or `file:size` on the `icechunk` asset (a directory has no single checksum). Info: no `canonical` link, because NOAA publishes no STAC for FDC. The `--data` pass reported the Kerchunk asset unreadable (404) because the provisional URL is not uploaded yet.
- **Registry pin.** Portolan pins the render extension at v2.0.0, so the collection declares v2.0.0 and not v2.1.0.
- **Thumbnail.** The spec requires one for geospatial collections. It is a 7 KB PNG in `catalog/`, rendered from the store.

Kerchunk was dropped after these findings (see stage 1b in section 10).

### Two-week build (2026-10-21)

GOES-18 FDCC, 2025-01-07 to 2025-01-20, built on a laptop with 32 threads.

- **Size and speed.** 3,996 scans in about 28 minutes, about 2.5 scans per second. Each UTC day took about 110 s of header reads. Listing and committing took under 1 s each. The tagged snapshot needs 13.3 MB of manifests, about 3.3 KB per scan.
- **Manifests grow with the square of the commits.** Without splitting, each daily append rewrote the whole manifest of each array. After 14 daily commits the repository held 100 MB for 13.3 MB of live manifests. With `ManifestSplittingConfig` along `time` at 288 scans, an append writes only its own manifests: four 24-scan appends wrote 78 to 81 KB each. `Repository.rewrite_manifests` re-split the existing repository in one commit, from 8 manifest files to 73, with the same 13.3 MB and identical data.
- **Bad time stamps.** In three files, `t` is the fill value `-999` and the pixels are valid. The file at 2025-01-10T00:01:17.5Z (start and end stamps equal) decoded to 2000-01-01T11:43:21 and was stored there. The Mode 4 files at 2025-01-20 15:10 and 15:15Z also have `-999` in `time_bounds`, and CF time decoding failed for the whole file. The pipeline now uses the file-name midpoint for any `t` outside the scan's own stamps. A separate commit corrected the stored value.
- **A gap.** NOAA's bucket has no FDCC files from 2025-01-16T11:57Z to 15:02Z. That day has 252 scans, not 288.
- **Read-back.** All five variables of three sampled scans, including two of the repaired ones, are byte-identical to the raw netCDF.
- **Reading through the catalog.** `examples/palisades-frp.ipynb` reads `Power` and `Mask` over a 6 x 9 pixel box for all 3,996 scans in 103 s, one chunk per variable per scan, from the local manifests and NOAA's bucket.
- **Tags cannot be reused.** Icechunk refuses to create a tag with the name of a deleted tag. The first tag name, `palisades-v1`, is burned in the local repository.

Storage estimate for the Palisades window (about 7,200 scans), extrapolated from the 24-scan measurements and not yet measured at scale: Icechunk about 47 to 72 MB (6.5 to 10 KB per scan, and manifest growth under many appends is unverified), Kerchunk parquet about 30 MB, Kerchunk JSON about 365 MB. The raw netCDF would be about 1.6 GB (226 KB per scan) and is never downloaded or copied. The build reads headers only.
