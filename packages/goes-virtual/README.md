# goes-virtual

`goes-virtual` builds virtual Zarr cubes over NOAA GOES ABI netCDF files and writes them to Icechunk. A cube stores byte-range references into NOAA's public buckets and no pixel data.

The `goes-fdc` pipeline in this repository uses it to build the catalog's cube. [docs/architecture.md](../../docs/architecture.md) describes the method.

## Development

The package is a uv project with its own lock file, and needs Python 3.12.

```bash
cd packages/goes-virtual
uv sync
uv run ruff check
uv run mypy
uv run pytest            # unit tests, no network
uv run pytest -m live    # reads NOAA's GOES-18 bucket
```
