# AGENTS.md — GOES-18 ABI L2 FDCC (virtual Zarr)

Guidance for AI agents and automated clients working with this collection.

**One rule survives every edit to this file.** Every claim here is either quoted
from a source or measured from the data. If you cannot point at where a fact
came from, it does not belong in this file. An agent acting on an invented join
key or an invented column name produces a confident wrong answer, and nothing
downstream catches it.

## What this collection holds

A virtual Zarr cube over 3,996 GOES-18 CONUS Fire/Hot Spot Characterization
scans, 2025-01-07T00:02Z to 2025-01-20T23:57Z (measured from the `time`
coordinate). Dimensions `time` (3996) × `y` (1500) × `x` (2500). The Icechunk tag
`demo-2025-01` pins this snapshot. Pixel variables `Mask`, `DQF`, `Power`,
`Temp`, `Area`. Public root, provisional:
`https://data.source.coop/<ACCOUNT>/goes-fdc/`.

The orbital slot recorded in the NOAA files read for this catalog (2025-01-07
and 2025-01-08) is `GOES-West`. A satellite's slot can change over its life, so
check the `orbital_slot` attribute in the file for the date you need.

## Store layout

Measured on a one-hour build of the store (2025-01-08 07:00 to 08:00 UTC, 12
scans):

- The pixel variables `Mask`, `DQF`, `Power`, `Temp` and `Area` are virtual `time` × `y` × `x` arrays, chunked
  1 × 250 × 250 as in NOAA's files.
- NOAA's per-scan values are `time` variables: the fire pixel counts
  (`total_number_of_pixels_with_fires_detected` and the three
  `total_number_of_pixels_with_fire_*` counts), the three `*_outlier_pixel_count`
  values, the `minimum_`, `maximum_`, `mean_` and `standard_deviation_` of
  `fire_temperature`, `fire_area` and `fire_radiative_power`, and
  `percent_uncorrectable_GRB_errors` and `percent_uncorrectable_L0_errors`.
  In the test hour, `maximum_fire_radiative_power` of the first scan was
  2617.017 MW, the same value as in NOAA's file.
- `goes_imager_projection` is a scalar variable with NOAA's CF projection
  attributes. Each pixel variable's `grid_mapping` names it.
- The root attributes declare four conventions in `zarr_conventions`: `proj`
  v0.1, `spatial` v0.1, `stac` v0.1 and `license` v1. They hold `proj:wkt2`,
  `spatial:dimensions` (`["y", "x"]`), `spatial:shape` (`[1500, 2500]`),
  `spatial:transform` (`[2004.017315487541, 0.0, -2505021.6463773525, 0.0,
  -2004.017315487541, 4589199.764884492]`, in metres), `stac:link` to this
  collection, and `license` (`{"spdx": "CC0-1.0"}`). The transform equals the
  `proj:transform` of Planetary Computer's GOES-18 CONUS `goes-cmi` items.

## Source bucket

Measured on 2026-10-06 against `https://noaa-goes18.s3.amazonaws.com`:

- Anonymous listing and Range requests work. A Range request returned `206`
  and `Accept-Ranges: bytes`. The bucket CORS rule allows `*` for GET.
- Keys are `ABI-L2-FDCC/<YYYY>/<DDD>/<HH>/<filename>`.
- Filenames look like
  `OR_ABI-L2-FDCC-M6_G18_s20250080301172_e20250080303545_c20250080304133.nc`.
  The `s`, `e` and `c` stamps are start, end and creation: year, day of year,
  hour, minute, second, tenths of a second.

## File layout (measured on the scan above)

| Variable | Shape | dtype | Chunks | Filter | Attributes |
|---|---|---|---|---|---|
| `Mask` | 1500 × 2500 | int16 | 250 × 250 | gzip + shuffle | `_FillValue` `-99` |
| `DQF` | 1500 × 2500 | uint8 | 250 × 250 | gzip + shuffle | `_FillValue` 255 |
| `Power` | 1500 × 2500 | float32 | 250 × 250 | gzip + shuffle | units MW, `_FillValue` `-9` |
| `Temp` | 1500 × 2500 | uint16 | 250 × 250 | gzip + shuffle | units K, `scale_factor` 0.05493667, `add_offset` 400, `_FillValue` 65535 |
| `Area` | 1500 × 2500 | uint16 | 250 × 250 | gzip + shuffle | units m2, `scale_factor` 60.98, `add_offset` 4000, `_FillValue` 65535 |

Each file also contains a scalar `t` (seconds since 2000-01-01 12:00:00) and
`time_bounds`. The `Mask` and `DQF` codes are in the `flag_values` and
`flag_meanings` attributes, and the catalog `../README.md` tabulates them. Fire
pixels are `Mask` codes 10 to 15 and 30 to 35 (measured from `flag_meanings` on
the scan above).

## How to read it

One asset, `icechunk`, with a working recipe in `README.md`. All five variables
of three sampled scans read back byte-identical to the raw netCDF from the local
store. The Source Cooperative URL is untested.

- Every pixel read is a Range request to
  `https://noaa-goes18.s3.amazonaws.com/ABI-L2-FDCC/...`. Opening the Icechunk
  repo without authorizing that prefix fails.
- Open with `consolidated=False`. The `chunks={}` argument needs `dask`, which
  is not a requirement for reading.
- Open with `decode_coords="all"`, as `xarray:open_kwargs` says, to make
  `goes_imager_projection` a coordinate. rioxarray then finds the CRS through
  `grid_mapping`. Without it, `rio.crs` is `None` (measured).

## Quirks that produce silently wrong answers

- **Raw integers.** Open with `mask_and_scale=False` to get NOAA's stored values.
  With the default, `Temp` and `Area` decode to float64 through `scale_factor`
  and `add_offset`, and fill values become NaN. Measured `Temp` scaling:
  `scale_factor` 0.05493667, `add_offset` 400, so a decoded value is never below
  400 K.
- **Fill values.** `Power` uses `-9` and `Mask` uses `-99`. A sum over `Power`
  without `where(Power > 0)` includes them. Measured over the box 118.70 W to
  118.45 W, 34.00 N to 34.15 N at 2025-01-08T07:12Z: the sum of positive
  `Power` is 26,255 MW.
- **Not latitude and longitude, and not metres.** `x` and `y` are ABI scan
  angles in radians on the geostationary fixed grid (`grid_mapping` is
  `goes_imager_projection`). The CRS in `proj:wkt2` is in metres, which are the
  scan angle times `perspective_point_height` (35786023 m). rioxarray's
  `rio.transform()` is computed from `x` and `y`, so it is in radians (measured
  step 5.6e-05). Use `spatial:transform` or the asset's `proj:transform` for
  metres. With them and `proj:wkt2`, `pyproj` placed the corner and centre pixels
  within 0.001 m of NOAA's published fixed-grid equations (measured).
- **Time is mid-scan.** `time` comes from each file's `t` and falls between the
  start and end stamps in the filename, for example 19:57:35 for a scan that
  starts 19:56:17. When a file's `t` is not usable, `time` is the midpoint of
  the start and end stamps in the filename instead.
- **A fill value can mean a missing variable.** When a file has no array for
  one of the five pixel variables, the build adds an array with no chunk
  references for that scan (`virtualize.fill_missing`), so every read returns
  the fill value. The build log gives the file name.
- **Gaps.** NOAA's bucket can have no file for a scan, and the cube then has no
  time step for it. Do not assume a fixed 5-minute spacing along `time`. A line
  plot joins the two sides of a gap, which hides it.
- **Scene extent.** The collection bbox is NOAA's `geospatial_lat_lon_extent`
  for this scene and crosses the antimeridian (west 175.6, east `-89.6`).
- **Reprocessing.** Each chunk read sends `If-Unmodified-Since` with the time the
  reference was written. NOAA's bucket answers `412` for a file modified after
  that time (measured with a date before a file's `Last-Modified`). Icechunk
  then stops with `the checksum of the object owning the virtual chunk has changed`. It does not compare bytes, so a re-upload of identical bytes also
  stops the read.

## Structure

Assets and structural links resolve relative to the object that carries them.
Catalogs here carry no `self` link, so a client tracks its own location. The
data assets use absolute `https` hrefs built from the public base URL.
