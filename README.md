# goes-fdc-catalog

A [Portolan](https://www.portolan-sdi.org/) catalog of NOAA's GOES ABI Fire/Hot Spot Characterization (FDC) as a **virtual Zarr cube**. The cube holds byte-range references into the raw netCDF in NOAA's public `noaa-goes*` buckets. It copies no pixel data and needs no server.

This is a reference implementation for [portolan-spec#132](https://github.com/portolan-sdi/portolan-spec/issues/132), which defers a normative Zarr profile until real Zarr datasets have been tested in catalogs.

Status: pilot. Stage 1 runs locally on the Palisades fire window (GOES-18 `ABI-L2-FDCC`, 2025-01-07 to 2025-01-31). Nothing is published yet.

## Read first

[docs/rfd/0001-goes-fdc-virtual-zarr.md](docs/rfd/0001-goes-fdc-virtual-zarr.md) has the design: data access, components, flow, open questions, and the stage 1 findings.

## Layout

| Path | What it is |
|---|---|
| `catalog/` | The published catalog (STAC JSON, README, AGENTS.md). Synced 1:1 to Source Cooperative |
| `pipeline/` | The VirtualiZarr job: list NOAA keys, virtualize, append to Icechunk, export Kerchunk |
| `local/` | Gitignored pipeline output (Icechunk repo, Kerchunk parquet) |
| `docs/` | Design document and accepted validator findings |
| `tools/`, `tests/` | Publish tooling and CI gates from the Portolan catalog template |

## Run it

This project uses [uv](https://docs.astral.sh/uv/). It creates `.venv` and installs the locked dependencies.

```bash
uv sync
uv run pytest                        # unit tests, no network
uv run goes-fdc build --start 2025-01-07T18:00 --end 2025-01-07T20:00 --out local/smoke
uv run python tests/run_all.py       # catalog gates
```

`goes-fdc build` lists scans in the window, reads their headers, appends the new ones to `local/smoke/icechunk`, and writes Kerchunk parquet under `local/smoke/refs/`. A second run with the same window adds nothing.

## Publish

```bash
uv run python tools/publish.py            # dry run
```

The storage path in `catalog.publish.yaml` is provisional. Confirm it with Source Cooperative before any `--confirm` upload.

## License

Apache-2.0 for the code in this repository. NOAA produces the data. A license value for the catalog is an open question in the design document.
