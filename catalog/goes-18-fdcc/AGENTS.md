# AGENTS.md — GOES-18 ABI L2 FDCC (virtual Zarr)

Guidance for AI agents and automated clients working with this collection.

**One rule survives every edit to this file.** Every claim here is either quoted
from a source or measured from the data. If you cannot point at where a fact
came from, it does not belong in this file. An agent acting on an invented join
key or an invented column name produces a confident wrong answer, and nothing
downstream catches it.

## What this collection holds

A virtual Zarr cube of GOES-18 CONUS Fire/Hot Spot Characterization scans, with
the dimensions `time`, `y` and `x`. The time extent is in the collection's
`extent` and in `cube:dimensions`. Public root, provisional:
`https://data.source.coop/<ACCOUNT>/goes-fdc/`.

**Read the variable names from the collection, not from this file.**
`cube:variables` in `collection.json` lists every variable in the store, with
its dimensions, unit and description. The `icechunk` asset's `bands` gives the
data type and the nodata value of each pixel variable.

The `orbital_slot` attribute in NOAA's files gives the satellite's slot. A
satellite's slot can change over its life, so check it for the date you need.

## Store layout

- The pixel variables are virtual `time` × `y` × `x` arrays. Their chunks are
  NOAA's chunks, one scan by 250 × 250 pixels, each a byte range in a NOAA
  file.
- NOAA's per-scan summary values are `time` arrays: counts, outlier counts and
  statistics. In `cube:variables`, they are the data variables whose only
  dimension is `time`.
- The `auxiliary` variable in `cube:variables` holds NOAA's CF projection
  attributes. Each pixel variable names it in `grid_mapping`.
- The root attributes declare the `proj` v0.1, `spatial` v0.1, `stac` v0.1 and
  `license` v1 conventions in `zarr_conventions`. They hold `proj:wkt2`,
  `spatial:dimensions`, `spatial:shape` and `spatial:transform` in metres, a
  `stac:link` to this collection, and the license.
- `spatial:transform` equals the asset's `proj:transform`. Both equal the
  `proj:transform` of Planetary Computer's GOES-18 CONUS `goes-cmi` items
  (measured).

## Source bucket

Measured against `https://noaa-goes18.s3.amazonaws.com`:

- Anonymous listing and Range requests work. A Range request returned `206`
  and `Accept-Ranges: bytes`. The bucket CORS rule allows `*` for GET.
- Keys are `ABI-L2-FDCC/<YYYY>/<DDD>/<HH>/<filename>`.
- Filenames look like
  `OR_ABI-L2-FDCC-M6_G18_s20250080301172_e20250080303545_c20250080304133.nc`.
  The `s`, `e` and `c` stamps are start, end and creation: year, day of year,
  hour, minute, second, tenths of a second.
- Each pixel variable in a file is 1500 × 2500, with 250 × 250 HDF5 chunks and
  gzip and shuffle filters. Its CF attributes give its units, fill value, and
  any `scale_factor` and `add_offset`.
- The fire mask codes are in its `flag_values` and `flag_meanings` attributes,
  and the catalog `../README.md` tabulates them. Fire pixels are codes 10 to 15
  and 30 to 35 (measured from `flag_meanings`).

## How to read it

One asset, `icechunk`, with a working recipe in `README.md`. Sampled scans read
back byte-identical to NOAA's netCDF for every pixel variable (measured). The
Source Cooperative URL is untested.

- Every pixel read is a Range request to
  `https://noaa-goes18.s3.amazonaws.com/ABI-L2-FDCC/...`. Opening the Icechunk
  repo without authorizing that prefix fails.
- Open with `consolidated=False`. The `chunks={}` argument needs `dask`, which
  is not a requirement for reading.
- Open with `decode_coords="all"`, as `xarray:open_kwargs` says, to make the
  `grid_mapping` variable a coordinate. rioxarray then finds the CRS. Without
  it, `rio.crs` is `None` (measured).

## Quirks that produce silently wrong answers

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
- **Time is mid-scan.** `time` comes from the time value in each NOAA file and
  falls between the start and end stamps in the filename, for example 19:57:35
  for a scan that starts 19:56:17. When a file's time value is not usable,
  `time` is the midpoint of the start and end stamps in the filename instead.
- **A fill value can mean a missing variable.** When a file has no array for a
  pixel variable, the build adds an array with no chunk references for that
  scan (`virtualize.fill_missing`), so every read returns the fill value. The
  build log gives the file name.
- **Gaps.** NOAA's bucket can have no file for a scan, and the cube then has no
  time step for it. Do not assume a fixed 5-minute spacing along `time`. A line
  plot joins the two sides of a gap, which hides it.
- **Scene extent.** The collection bbox is NOAA's `geospatial_lat_lon_extent`
  for this scene and crosses the antimeridian (west 175.6, east `-89.6`).
- **Reprocessing.** Each chunk read sends `If-Unmodified-Since` with the time the
  reference was written. NOAA's bucket answers `412` for a file modified after
  that time (measured with a date before a file's `Last-Modified`). Icechunk
  then stops with `the checksum of the object owning the virtual chunk has
  changed`. It does not compare bytes, so a re-upload of identical bytes also
  stops the read.

## Structure

Assets and structural links resolve relative to the object that carries them.
Catalogs here carry no `self` link, so a client tracks its own location. The
data assets use absolute `https` hrefs built from the public base URL.
