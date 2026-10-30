# goes-virtual

`goes-virtual` builds virtual Zarr cubes over NOAA GOES ABI netCDF files and writes them to Icechunk. A cube holds byte-range references into NOAA's public buckets. It holds no pixel data.

The `goes-fdc` pipeline in this repository uses it to build the full-grid GOES-18 FDCC cube for the catalog. Another project can pin it from git and build its own cubes, for example a cube cropped to one area.

## Install

The package is a uv project. Its Python floor is 3.12.

```bash
cd packages/goes-virtual
uv sync
uv run pytest            # unit tests, no network
uv run pytest -m live    # reads NOAA's GOES-18 bucket
uv run mypy
uv run ruff check
```

Another uv project pins it from git by tag:

```toml
[tool.uv.sources]
goes-virtual = { git = "ssh://git@github.com/mmidzik/goes-fdc-catalog", subdirectory = "packages/goes-virtual", tag = "goes-virtual-v0.1.0" }
```

## Use

```python
from datetime import UTC, datetime

import icechunk
from goes_virtual import grid, listing, store, virtualize

start = datetime(2025, 1, 8, 3, tzinfo=UTC)
end = datetime(2025, 1, 8, 4, tzinfo=UTC)
scans = [key.ref() for key in listing.list_scans("G18", "ABI-L2-FDCF", start, end)]

cube = virtualize.build_cube(scans, keep=["Power", "Mask"])
site = grid.crop(cube.dataset, (-118.7, 34.0, -118.4, 34.2))

prefix = "https://noaa-goes18.s3.amazonaws.com/"
repo = store.open_repo(icechunk.local_filesystem_storage("site/icechunk"), prefix)
snapshot = store.write(repo, site, "2025-01-08T03Z")
```

A caller that lists scans another way builds `ScanRef(url, start, end)` itself. The URL is the object's public `https://` URL. `start` and `end` are the scan start and end in UTC, with a timezone. A naive datetime is an error.

## Modules

| Module | Does |
|---|---|
| `scan.py` | Parses a NOAA object key. Defines `ScanRef`, the input to virtualization. |
| `listing.py` | Lists the scans of one product in a time window. One anonymous list call goes to each hour prefix. |
| `layout.py` | Reads which variables a cube keeps from the file's own metadata. |
| `virtualize.py` | Reads file headers with VirtualiZarr, checks each scan, and stacks the scans along `time`. |
| `grid.py` | Gives the CRS, the affine transform, the store root attributes, and the site crop. |
| `store.py` | Opens the Icechunk repository, and writes or appends a cube. |
| `cadence.py` | Gives the nominal time between scans for an ABI scan mode and scene. |

## Object keys

`parse_key` reads keys in NOAA's layout:

```
{product}/{year}/{day of year}/{hour}/OR_{product}-M{mode}[C{band}]_{satellite}_s{start}_e{end}_c{created}.nc
```

The key gives the product, the scan mode, the band when the product has one, the satellite, and the start, end and creation stamps. A stamp is year, day of year, hour, minute, second and tenths, in UTC. The prefix product of a mesoscale product has no sector number. `ABI-L2-FDCM/` holds `ABI-L2-FDCM1` and `ABI-L2-FDCM2` files.

## The cube

### Variables

`layout` reads the variables from the file's dimensions and its CF and ACDD attributes:

| Role | Rule |
|---|---|
| Pixel variables | The data variables on the `y` × `x` grid |
| Per-scan values | The scalars with a CF `cell_methods` attribute |
| Projection | The variable that the pixel variables name in `grid_mapping` |
| Scene extent | The scalar with the ACDD `geospatial_westbound_longitude` attribute |

`build_cube(scans, keep=...)` keeps only the pixel and per-scan variables in `keep`. `keep=None` keeps all of them. The projection and the scene extent always stay. A name in `keep` that the file does not have is an error.

Pixel variables stay virtual. The coordinates, the projection, the per-scan values and the scene extent are read as values.

### Time

The `time` coordinate is the file's `t` variable, the middle of the scan, in UTC. Some files carry the fill value -999 in `t`. When `t` is more than 1 minute outside the scan's start and end stamps, the build uses the middle of the stamps and logs a warning.

### Root attributes

The cube's root attributes are the GeoZarr conventions only, written with `zarr-cm`:

| Convention | Attributes |
|---|---|
| `proj` | `proj:wkt2` |
| `spatial` | `spatial:dimensions`, `spatial:shape`, and `spatial:transform` in metres |
| `stac` | `stac:link` to the collection, when the caller gives a collection URL |
| `license` | `{"spdx": "CC0-1.0"}` by default |

`x` and `y` stay in radians, as CF and NOAA define them. The transform is in metres, which is scan angle times the satellite height.

`grid.crop` cuts a cube to the whole source chunks that cover a box in EPSG:4326 degrees. It rewrites `spatial:shape` and `spatial:transform` for the cropped grid. It refuses a crop that reaches past the Earth disk.

### Scan checks

- **Grid and encoding.** Every scan in a cube must have the same `proj` and `spatial` attributes, and the same chunks, data type, fill value, codecs and CF scaling on each pixel variable. A scan that differs raises `EncodingMismatch`. NOAA changes these over the life of a satellite, so one satellite can need more than one cube.
- **Aborted scans.** A scan with equal start and end stamps and only fill values is skipped.
- **Missing variables.** A scan that lacks a variable of the layout gets a stand-in with no chunk references. A read of the stand-in returns the fill value.
- **Appends.** `store.write` refuses an append whose signature differs from the store, or that adds or drops a variable along `time`.

`build_cube` returns `None` when no scan in the batch is usable. It returns a `VirtualCube` otherwise. `VirtualCube.scan_modes` holds the `timeline_id` and `scene_id` of each scan, in the order of `time`. `cadence.time_step` takes them and gives the nominal step as an ISO 8601 duration.

## Store

`store.open_repo(storage, prefix, split_time_steps)` opens or creates the repository. The caller gives the `icechunk.Storage`. `prefix` is the URL prefix of the scans, which the repository authorizes as an HTTP virtual chunk container. A reader must authorize the same prefix.

`split_time_steps` sets the time steps in one manifest. Use it for a cube that grows by appends. Without a split, each append rewrites every manifest, and the repository grows with the square of the number of commits.

## Errors

The package raises `ValueError` and its subclasses for bad input and for scans that cannot join a cube. It does not depend on pystac.
