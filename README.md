# goes-fdc-catalog

A [Portolan](https://github.com/portolan-sdi/portolan-spec) catalog mirroring
**NOAA GOES ABI fire detections** (Fire/Hot Spot Characterization, FDC) as
**virtual Zarr cubes**, one collection per satellite and scan sector. The first
collection is GOES-18 CONUS.

Catalog metadata and the build pipeline are in this repository. The Icechunk
repository for each cube goes to Source Cooperative. The pixel data stays in
NOAA's public [buckets on AWS S3](https://registry.opendata.aws/noaa-goes/), and
the cube contains only byte-range references to it.

> **Status: demo, built locally. Publishing to Source Cooperative is TODO.**

- **Published catalog**: TODO, not on Source Cooperative yet
- **Upstream**: https://registry.opendata.aws/noaa-goes/ (NOAA and NESDIS
  produce the data and remain the authoritative source)
- **Methods and design**: [docs/architecture.md](docs/architecture.md)

[catalog/README.md](catalog/README.md) describes the data and how to read it.
[docs/architecture.md](docs/architecture.md) explains how the build makes the
cube, and what this demo found about Zarr in Portolan. To see it work, run
[examples/palisades-frp.ipynb](examples/palisades-frp.ipynb). It starts at
`catalog/catalog.json`, finds the cube through the collection metadata, and
plots fire radiative power over the Palisades burn area.

## What it publishes

```
catalog/
  catalog.json                  root: GOES FDC
  goes-18-fdcc/collection.json  GOES-18, CONUS sector
    icechunk/                   the cube, on Source Cooperative (not in git)
```

Each collection has one data asset, an Icechunk repository. It contains
manifests, never pixels, and every read fetches chunk byte ranges from NOAA's
bucket. The Zarr asset is outside the Portolan conformance surface
([portolan-spec#132](https://github.com/portolan-sdi/portolan-spec/issues/132)).

## Design decisions

**Virtual, not copied.** GOES FDC is a raster grid per scan, with fire as a few
classes among many. The cube keeps the full grid and copies none of it.

**We rely on NOAA's S3 bucket.** Every pixel read is a Range request to NOAA's
bucket. If NOAA changes a file after the reference was written, Icechunk stops
the read instead of returning wrong bytes.

**One grid per cube.** A virtual cube inherits the grid of the files it
references, and NOAA changes the grid over a satellite's life. The build checks
every scan and stops on a mismatch.

**One collection per satellite and sector.** Collection ids follow
`goes-<satellite>-fdc<sector>`, in the order of NOAA's buckets and Earth Engine
(`NOAA/GOES/18/FDCC`). A new satellite or sector is a sibling collection, and no
existing URL moves.

**No server.** Readers hit static files on Source Cooperative and NOAA's bucket.

## The pipeline

| Module                                | Does                                                                 |
| ------------------------------------- | -------------------------------------------------------------------- |
| `pipeline/src/goes_fdc/keys.py`       | Lists the scans in a time window from the NOAA bucket.               |
| `pipeline/src/goes_fdc/virtualize.py` | Reads each netCDF header with VirtualiZarr and checks the grid.      |
| `pipeline/src/goes_fdc/store.py`      | Appends new time steps to the Icechunk repo.                         |
| `pipeline/src/goes_fdc/cli.py`        | The `goes-fdc build` command. One commit per UTC day, and resumable. |
| `pipeline/src/goes_fdc/collection.py` | Writes `collection.json` from facts read from the store.             |
| `pipeline/src/goes_fdc/thumbnail.py`  | Renders the collection thumbnail.                                    |
| `tools/publish.py`                    | Syncs `catalog/` to the bucket. From the template.                   |
| `tools/upload_data.py`                | Uploads the Icechunk repo. From the template.                        |
| `.github/workflows/update.yml`        | Appends new scans to the published store. Manual trigger.            |

```bash
uv sync
uv run goes-fdc build --start 2025-01-07T00:00 --end 2025-01-21T00:00
```

The build reads netCDF headers only and needs no NOAA credentials. It writes the
store to `local/publish/goes-18-fdcc/icechunk`.

## Working on this repository

Python dependencies use [uv](https://docs.astral.sh/uv/).

```bash
uv sync
uv run pytest                          # unit tests, no network
uv run python tests/run_all.py         # gates: conformance, links, STAC validity
uv run python -m goes_fdc.collection \
    --public-base https://data.source.coop/<ACCOUNT>/goes-fdc
uv run python tools/publish.py         # dry run: catalog metadata
uv run python tools/upload_data.py     # dry run: the Icechunk repo
```

The STAC gate uses stac-check, which does not validate the extension schemas of
the collection (see [docs/conformance.md](docs/conformance.md)). Before a
release, also run stac-node-validator, the release that the Portolan registry
runs. It needs Node.js 22.12 or later, and it does not run in CI:

```bash
npx --yes stac-node-validator@2.0.0 catalog/
```

Data files never enter git. `.gitignore` blocks the common formats, plus
`local/` for pipeline output and staged data.

## Next steps

- **Extend the time range** on a cloud machine with the same `goes-fdc build`
  command.
- **Publish to Source Cooperative.** Replace the `<ACCOUNT>` placeholder in
  `catalog.publish.yaml`, the collection asset hrefs and the published docs,
  then regenerate the collection. `tools/publish.py` refuses `--confirm` while
  the placeholder is set. Check that Source Cooperative supports the conditional
  writes Icechunk needs.
- Run the update workflow once, then decide whether to schedule it.

## Acknowledgements

Earthmover's post
[Cloud-optimizing the GOES-16 archive as Virtual Zarr](https://www.earthmover.io/blog/virtual-zarr/)
by Tom Nicholas is the source of the approach in this repository. Thank you to
Tom Nicholas and the Earthmover team.

Chris Holmes's
[firms-catalog](https://github.com/portolan-mirrors/firms-catalog) is the model
for how this repository is laid out and documented.

## License

Code: Apache-2.0, see `LICENSE`. Data: CC0-1.0, produced by NOAA. See
[catalog/README.md](catalog/README.md#license).
