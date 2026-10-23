# goes-fdc-catalog

A [Portolan](https://github.com/portolan-sdi/portolan-spec) catalog mirroring
**NOAA GOES ABI fire detections** (Fire/Hot Spot Characterization, FDC) as
**virtual Zarr cubes**, one collection per satellite and scan sector. The first
collection is GOES-18 CONUS.

Catalog metadata and the build pipeline live in this repository. The Icechunk
repository that holds the cube goes to Source Cooperative. The pixel data stays
in NOAA's public `noaa-goes18`
[bucket on AWS S3](https://registry.opendata.aws/noaa-goes/), and the cube holds
only byte-range references to it.

> **Status: demo, built locally. Publishing to Source Cooperative is TODO.**

- **Published catalog**: TODO, not on Source Cooperative yet
- **STAC root**: TODO, same
- **Browse it in the Portolan browser**: TODO, needs the published STAC root
- **Upstream**: https://registry.opendata.aws/noaa-goes/ (NOAA and NESDIS
  produce the data and remain the authoritative source)
- **Methods and design**: [docs/architecture.md](docs/architecture.md)

Start with the catalog's own documentation. [catalog/README.md](catalog/README.md) describes the data and how to read it. [docs/architecture.md](docs/architecture.md) explains how the build makes the cube, and what this demo found about Zarr in Portolan. Everything below is about how this
repository builds and publishes the catalog.

To see it work, run
[examples/palisades-frp.ipynb](examples/palisades-frp.ipynb). It starts at
`catalog/catalog.json`, finds the cube through the collection metadata, and
plots fire radiative power over the Palisades burn area.

## What it publishes

One catalog for GOES FDC, with one collection per satellite and scan sector. The
first collection, `goes-18-fdcc`, is the GOES-18 CONUS product. It holds 3,996 scans from 2025-01-07 to 2025-01-20 UTC, one 1500 × 2500 grid about
every 5 minutes, with five variables: `Mask`, `DQF`, `Power`, `Temp`, `Area`.

```
catalog/
  catalog.json                  root: GOES FDC
  goes-18-fdcc/collection.json  GOES-18, CONUS sector
    icechunk/                   the cube, on Source Cooperative (not in git)
```

The one data asset is an Icechunk repository. It holds manifests, never pixels.
Every read fetches chunk byte ranges from NOAA's bucket. Reading it needs
`icechunk`, `zarr` and `xarray`.

This catalog is a test of Zarr in a Portolan catalog. Portolan defers a
normative Zarr profile until real Zarr datasets have been tested in catalogs
([portolan-spec#132](https://github.com/portolan-sdi/portolan-spec/issues/132)),
so the Zarr asset is outside the Portolan conformance surface. The findings are
in
[docs/architecture.md](docs/architecture.md#zarr-in-portolan-findings-from-this-demo).

## Design decisions worth knowing

**Virtual, not copied.** GOES FDC is a raster grid per scan, with fire as a few
classes among many. The cube keeps the full grid and copies none of it.

**We rely on the AWS S3 bucket.** Every pixel read is a Range request to
`https://noaa-goes18.s3.amazonaws.com`. The catalog has no copy of its own. If
NOAA changes a file after the reference was written, Icechunk stops the read
instead of returning wrong bytes.

**One grid per cube.** A virtual cube inherits the grid and encoding of the
files it references, and NOAA changed these over the life of GOES-18. The build
checks a signature of every scan and stops on a mismatch. This could be adjusted
in future iterations.

**One collection per satellite and sector.** The collections are direct
children of the root catalog, with no sub-catalog level. Collection ids follow
`goes-<satellite>-fdc<sector>`, in the order of NOAA's buckets and Earth Engine
(`NOAA/GOES/18/FDCC`). A new satellite or sector is a sibling collection, and no
existing URL moves.

**No server.** Readers hit static files on Source Cooperative and NOAA's bucket.
The update job is a GitHub Action with a manual trigger.

The reasons and the measurements behind each decision are in
[docs/architecture.md](docs/architecture.md).

## The pipeline

| Module                                | Does                                                                                                                                     |
| ------------------------------------- | ---------------------------------------------------------------------------------------------------------------------------------------- |
| `pipeline/src/goes_fdc/keys.py`       | Parses NOAA key names and lists scans in a time window with an anonymous S3 listing.                                                     |
| `pipeline/src/goes_fdc/virtualize.py` | Reads each netCDF header with VirtualiZarr (`HDFParser`), checks each scan's grid and encoding signature, and stacks scans along `time`. |
| `pipeline/src/goes_fdc/store.py`      | Opens the Icechunk repo (local path or `s3://`) and appends new time steps. Refuses a cube whose signature differs from the store's.     |
| `pipeline/src/goes_fdc/cli.py`        | The `goes-fdc build` command. One commit per UTC day. Resumable: scans already in the store are skipped.                                 |
| `pipeline/src/goes_fdc/collection.py` | Writes `collection.json` from facts read from the store.                                                                                 |
| `pipeline/src/goes_fdc/thumbnail.py`  | Renders the collection thumbnail from one scan.                                                                                          |
| `tools/publish.py`                    | Syncs `catalog/` to the bucket. Template-provided; never widened beyond `catalog/`.                                                      |
| `tools/upload_data.py`                | Uploads staged data files, including the Icechunk repo. Template-provided.                                                               |
| `.github/workflows/update.yml`        | Appends new scans to the published store. Draft, manual trigger, not yet run.                                                            |

```bash
uv sync
uv run goes-fdc build --start 2025-01-07T00:00 --end 2025-01-21T00:00
```

The build reads netCDF headers only and needs no NOAA credentials. It writes the
store to `local/publish/goes-18-fdcc/icechunk`, the path that
`tools/upload_data.py` uploads.

## Working on this repository

Python dependencies use [uv](https://docs.astral.sh/uv/). It creates `.venv` and
installs the locked versions.

```bash
uv sync
uv run pytest                          # unit tests, no network
uv run python tests/run_all.py         # gates: conformance, links, STAC validity
uv run rashid check catalog --schema   # the validator directly
```

Write the collection from the store, render the thumbnail, then dry-run the
uploads:

```bash
uv run python -m goes_fdc.collection \
    --public-base https://data.source.coop/<ACCOUNT>/goes-fdc
uv run --group viz python -m goes_fdc.thumbnail --time 2025-01-08T06:00 \
    --out catalog/goes-18-fdcc/thumbnail.png
uv run python tools/publish.py          # dry run: catalog metadata
uv run python tools/upload_data.py      # dry run: the Icechunk repo
uv run --group examples jupyter nbconvert --to notebook --execute --inplace \
    examples/palisades-frp.ipynb
```

Data files never enter git. `.gitignore` blocks the common formats, plus
`local/` for pipeline output and staged data.

## Status and TODO

Done:

- Local pipeline over the NOAA bucket: append, resume, one commit per day, and a
  grid and encoding check on every scan.
- The two-week cube, built locally: 3,996 scans, tagged `demo-2025-01` in the
  Icechunk repository.
- The catalog, with the root and the `goes-18-fdcc` collection with the
  Icechunk asset, thumbnail, README and AGENTS.md at each level.
- `examples/palisades-frp.ipynb`, which reads the cube through the catalog.

TODO:

- **Extend to two years** on a cloud machine. The pipeline is the same. Only the
  window and the machine change.
- **Publish to Source Cooperative.** The `<ACCOUNT>` placeholder is in
  `catalog.publish.yaml`, in the collection asset hrefs, and in the published
  READMEs and AGENTS.md files. Set it in all of them, regenerate the collection,
  then fill in the links at the top of this file. `tools/publish.py` refuses
  `--confirm` while the placeholder is set. Install the upload dependency with
  `uv sync --group upload`. Check that Source Cooperative supports the
  conditional writes Icechunk needs. After the upload, run
  `rashid check catalog --schema --data --live --live-base-url <public base>`
  and re-run the notebook against the public catalog.
- Run the update workflow once, then decide whether to schedule it.

## Acknowledgements

Earthmover's post
[Cloud-optimizing the GOES-16 archive as Virtual Zarr](https://www.earthmover.io/blog/virtual-zarr/)
(Tom Nicholas, June 2026) is the source of the approach in this repository. This
catalog uses the same method for the GOES FDC product and publishes the result
as a Portolan catalog. Thank you to Tom Nicholas and the Earthmover team.

Chris Holmes's
[firms-catalog](https://github.com/portolan-mirrors/firms-catalog) is the model
for how this repository is laid out and documented, from the README structure to
the published agent guides. Thank you to Chris Holmes for that guidance, and for
the leadership on Portolan that makes catalogs like this one possible.

## License

Code: Apache-2.0, see `LICENSE`. Data: CC0-1.0, produced by NOAA. See [catalog/README.md](catalog/README.md#license).
