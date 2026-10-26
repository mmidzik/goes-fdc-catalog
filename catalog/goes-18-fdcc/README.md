# Fire/hot spot characterization from GOES-18 (virtual Zarr)

A virtual Zarr cube of GOES-18 CONUS Fire/Hot Spot Characterization scans, with
its time extent in the collection's `extent`. The cube holds byte-range references
into NOAA's `ABI-L2-FDCC` netCDF files in the public `noaa-goes18` bucket and
copies no pixel data. The variables, the fire mask and quality codes, and the
grid are described in the [catalog README](../README.md).

One asset, `icechunk`, holds the cube as an Icechunk repository. The branch
`main` has the latest scans, and a tag pins a snapshot. Reading it needs `icechunk`, `zarr` and
`xarray`. The Zarr asset is outside the Portolan conformance surface
([portolan-spec#132](https://github.com/portolan-sdi/portolan-spec/issues/132)).

## License

CC0-1.0, from NOAA. See the [catalog README](../README.md#license) for the
source and NOAA's attribution requests.

## Provenance

NOAA and NESDIS produce the data and remain the authoritative source. This
collection mirrors product `ABI-L2-FDCC` in the `noaa-goes18` bucket
(<https://registry.opendata.aws/noaa-goes/>). The `updated` field holds the time
the collection was last built. There is no scheduled sync. The cube keeps any
gaps in NOAA's bucket.

## Access

Open the Icechunk repository. The NOAA bucket needs the `https` prefix
authorized as a virtual chunk container, with no credentials:

```python
import icechunk, xarray as xr

NOAA = "https://noaa-goes18.s3.amazonaws.com/"
config = icechunk.RepositoryConfig.default()
config.set_virtual_chunk_container(icechunk.VirtualChunkContainer(NOAA, icechunk.http_store()))
credentials = icechunk.containers_credentials({NOAA: icechunk.Credentials.HttpAccess()})

storage = icechunk.http_storage(
    "https://data.source.coop/<ACCOUNT>/goes-fdc/goes-18-fdcc/icechunk"
)
repo = icechunk.Repository.open(storage, config=config, authorize_virtual_chunk_access=credentials)
session = repo.readonly_session(branch="main")   # or tag="..." to pin a snapshot
ds = xr.open_zarr(session.store, consolidated=False, decode_coords="all")

power = ds.Power.isel(time=-1).values   # last scan, raw float32, fill value -9
```

The recipe is tested with `icechunk.http_storage` against a store served over
HTTP, in a clean environment with only `icechunk`, `zarr` and `xarray`, and with
NOAA read live. It returns the same values as a read from the local file
system. Without the virtual chunk
container, the read fails with "you need to authorize the virtual chunk
container". The Source Cooperative URL above is provisional and untested until
the collection is uploaded. For a worked example that starts from the catalog,
see `examples/palisades-frp.ipynb` in the
[source repository](https://github.com/mmidzik/goes-fdc-catalog).

Sampled scans read back byte-identical to NOAA's netCDF for every pixel
variable (measured).

- Every pixel read is a Range request to
  `https://noaa-goes18.s3.amazonaws.com/ABI-L2-FDCC/...`. Opening the
  repository without authorizing that prefix fails.
- Open with `consolidated=False`. The `chunks={}` argument needs `dask`, which
  is not a requirement for reading.
- Open with `decode_coords="all"`, as the asset's `xarray:open_kwargs` says, to
  make the `grid_mapping` variable a coordinate. rioxarray then finds the CRS.
  Without it, `rio.crs` is `None` (measured).

## Store layout

The collection names every variable. `cube:variables` gives each variable's
dimensions, unit and description. The `icechunk` asset's `bands` gives the data
type and the nodata value of each pixel variable.

- The pixel variables are virtual `time` × `y` × `x` arrays. Their chunks are
  NOAA's chunks, one scan by 250 × 250 pixels, each a byte range in a NOAA
  file.
- NOAA's per-scan summary values are `time` arrays: counts, outlier counts and
  statistics. In `cube:variables`, they are the data variables whose only
  dimension is `time`.
- `cube:variables` marks two scalars as `auxiliary`. Each pixel variable names
  one of them in `grid_mapping`, and it holds NOAA's CF projection attributes.
  The other holds NOAA's ACDD scene extent, the source of the collection
  `bbox`.
- The root attributes declare the `proj` v0.1, `spatial` v0.1, `stac` v0.1 and
  `license` v1 conventions in `zarr_conventions`. They hold `proj:wkt2`,
  `spatial:dimensions`, `spatial:shape` and `spatial:transform` in metres, a
  `stac:link` to this collection, and the license.
- `spatial:transform` equals the asset's `proj:transform`. Both equal the
  `proj:transform` of Planetary Computer's GOES-18 CONUS `goes-cmi` items
  (measured).
- A scan is identified by its `time` value, and a pixel by `time`, `y` and `x`.

## Source files

Measured against `https://noaa-goes18.s3.amazonaws.com`:

- Anonymous listing and Range requests work. A Range request returned `206`
  and `Accept-Ranges: bytes`. The bucket CORS rule allows `*` for GET.
- Keys are `ABI-L2-FDCC/<YYYY>/<DDD>/<HH>/<filename>`.
- File names look like
  `OR_ABI-L2-FDCC-M6_G18_s20250080301172_e20250080303545_c20250080304133.nc`.
  The `s`, `e` and `c` stamps are start, end and creation: year, day of year,
  hour, minute, second, tenths of a second.
- Each pixel variable in a file is 1500 × 2500, with 250 × 250 HDF5 chunks and
  gzip and shuffle filters. Its CF attributes give its units, fill value, and
  any `scale_factor` and `add_offset`.
- The `orbital_slot` attribute gives the satellite's slot. A satellite's slot
  can change over its life, so check it for the date you need.

## Traps

These produce a wrong answer with no error. The fire mask codes, the time of a
scan and the gaps along `time` are in the [catalog README](../README.md).

- **Raw integers.** Open with `mask_and_scale=False` to get NOAA's stored
  values. With the default, a variable with `scale_factor` and `add_offset`
  decodes to float64, and fill values become NaN. A decoded value is never
  below that variable's `add_offset`.
- **Fill values inside the number range.** Some nodata values in `bands` are
  negative numbers in a float or signed integer range. A sum that does not mask
  them includes them. Exclude values at or below zero before a sum of fire
  radiative power. Measured over the box 118.70 W to 118.45 W, 34.00 N to
  34.15 N at 2025-01-08T07:12Z: the sum of positive fire radiative power is
  26,255 MW.
- **Not latitude and longitude, and not metres.** `x` and `y` are ABI scan
  angles in radians on the geostationary fixed grid. The CRS in `proj:wkt2` is
  in metres, which are the scan angle times the `perspective_point_height` of
  the `grid_mapping` variable. rioxarray computes `rio.transform()` from `x` and
  `y`, so it is in radians (measured). Use `spatial:transform` or the asset's
  `proj:transform` for metres. With them and `proj:wkt2`, `pyproj` places the
  corner and centre pixels within 0.001 m of NOAA's published fixed-grid
  equations (measured).
- **A fill value can mean a missing variable.** When a file has no array for a
  pixel variable, the build adds an array with no chunk references for that
  scan, so every read returns the fill value. When a file has no per-scan
  value, the build stores the variable's fill value for that scan.
- **A line plot hides gaps.** It joins the two sides of a gap along `time`.
- **The bbox crosses the antimeridian.** The collection bbox is NOAA's scene
  extent, from west 175.6 to east -89.6.
- **Reprocessing.** Each chunk read sends `If-Unmodified-Since` with the time the
  reference was written. NOAA's bucket answers `412` for a file modified after
  that time (measured with a date before a file's `Last-Modified`). Icechunk
  then stops with `the checksum of the object owning the virtual chunk has
  changed`. It does not compare bytes, so a re-upload of identical bytes also
  stops the read.
