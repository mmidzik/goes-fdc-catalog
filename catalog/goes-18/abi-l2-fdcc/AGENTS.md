# AGENTS.md — GOES-18 ABI L2 FDCC (virtual Zarr)

Guidance for AI agents and automated clients working with this collection.

**One rule survives every edit to this file.** Every claim here is either quoted
from a source or measured from the data. If you cannot point at where a fact
came from, it does not belong in this file. An agent acting on an invented join
key or an invented column name produces a confident wrong answer, and nothing
downstream catches it.

## What this collection holds

A virtual Zarr cube over 24 GOES-18 CONUS Fire/Hot Spot Characterization scans,
2025-01-07T18:02Z to 19:57Z (measured from the `time` coordinate). Dimensions
`time` (24) × `y` (1500) × `x` (2500). Variables `Mask`, `DQF`, `Power`, `Temp`,
`Area`. Public root, provisional:
`https://data.source.coop/portolan-mirrors/goes-fdc-catalog/`.

## How to read it

Two assets, `icechunk` and `kerchunk`, with working recipes in `README.md`. Both
returned the same 24 scans and the same `Power` array when tested against a local
HTTP copy. The Source Cooperative URLs are untested.

- Every pixel read is a Range request to
  `https://noaa-goes18.s3.amazonaws.com/ABI-L2-FDCC/...`. Opening the Icechunk
  repo without authorizing that prefix fails.
- Open with `consolidated=False`. The `chunks={}` argument needs `dask`, which
  is not a requirement for reading.

## Quirks that produce silently wrong answers

- **Raw integers.** Open with `mask_and_scale=False` to get NOAA's stored values.
  With the default, `Temp` and `Area` decode to float64 through `scale_factor`
  and `add_offset`, and fill values become NaN. Measured `Temp` scaling:
  `scale_factor` 0.05493667, `add_offset` 400, so a decoded value is never below
  400 K.
- **Fill values.** `Power` uses `-9` and `Mask` uses `-99`. A sum over `Power`
  without `where(Power > 0)` includes them. Measured on the last scan: the sum
  of positive `Power` is 5215.4 MW over the whole grid.
- **Not latitude and longitude.** `x` and `y` are ABI scan angles in radians on
  the geostationary fixed grid (`grid_mapping` is `goes_imager_projection`). A
  point-in-box filter on lat/lon needs the projection first. The collection's
  `proj:wkt2` holds it.
- **Time is mid-scan.** `time` comes from each file's `t` and falls between the
  start and end stamps in the filename, for example 19:57:35 for a scan that
  starts 19:56:17.
- **Scene extent.** The collection bbox is NOAA's `geospatial_lat_lon_extent`
  for this scene and crosses the antimeridian (west 175.6, east -89.6).
- **Reprocessing.** The Icechunk repository checks that a NOAA file has not
  changed. The Kerchunk references do not. If NOAA replaces a file, Kerchunk can
  return wrong bytes silently.

## Structure

Assets and structural links resolve relative to the object that carries them.
Catalogs here carry no `self` link, so a client tracks its own location. The
data assets use absolute `https` hrefs built from the public base URL.
