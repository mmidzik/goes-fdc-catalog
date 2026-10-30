# AGENTS.md — GOES-18 ABI L2 FDCC (virtual Zarr)

Guidance for AI agents and automated clients working with this collection.
Every claim here is either quoted from a source or measured from the data.

A virtual Zarr cube of NOAA's GOES-18 Fire/Hot Spot Characterization scans for
the CONUS sector, one scan about every 5 minutes. Each pixel read is a Range
request into NOAA's netCDF files. A scan is identified by its `time` value, and
a pixel by `time`, `y` and `x`. NOAA's per-scan summary values share the `time` axis, so a per-scan value and
a pixel array match on `time`.

Read variable names from the metadata, not from this file. In
[`collection.json`](collection.json), `cube:variables` lists every variable with
its dimensions, unit and description. The `icechunk` asset's `bands` gives each
pixel variable's name, description, unit, data type and nodata value. The
recipe below finds its variable by description.

## Access

Open the `icechunk` asset with `icechunk` and `xarray`, and authorize NOAA's
bucket as a virtual chunk container. Pass the asset's `xarray:open_kwargs` to
`xarray.open_dataset`. This read takes every name and number from the metadata.
It sums positive fire radiative power over the Palisades fire:

```python
import json, urllib.request
import icechunk, pyproj, xarray as xr

COLLECTION = "https://data.source.coop/mmidzik/goes-fdc/goes-18-fdcc/collection.json"
asset = json.load(urllib.request.urlopen(COLLECTION))["assets"]["icechunk"]
frp = next(b for b in asset["bands"] if b["description"].lower() == "fire radiative power")

NOAA = "https://noaa-goes18.s3.amazonaws.com/"
config = icechunk.RepositoryConfig.default()
config.set_virtual_chunk_container(icechunk.VirtualChunkContainer(NOAA, icechunk.http_store()))
credentials = icechunk.containers_credentials({NOAA: icechunk.Credentials.HttpAccess()})
repo = icechunk.Repository.open(icechunk.http_storage(asset["href"]), config=config,
                                authorize_virtual_chunk_access=credentials)
ds = xr.open_dataset(repo.readonly_session(branch="main").store, **asset["xarray:open_kwargs"])

# Longitude and latitude to pixel indices, with proj:wkt2 and proj:transform.
to_grid = pyproj.Transformer.from_crs("EPSG:4326", pyproj.CRS.from_wkt(asset["proj:wkt2"]), always_xy=True)
a, _, c, _, e, f = asset["proj:transform"]
xs, ys = to_grid.transform([-118.70, -118.45], [34.00, 34.15])
cols = sorted(int((x - c) // a) for x in xs)
rows = sorted(int((y - f) // e) for y in ys)

scan = ds[frp["name"]].sel(time="2025-01-08T07:12", method="nearest")
box = scan.isel(y=slice(rows[0], rows[1] + 1), x=slice(cols[0], cols[1] + 1))
print(str(scan.time.values)[:19], box.shape, f"{float(box.where(box > 0).sum()):,.0f} {frp['unit']}")
# 2025-01-08T07:12:35 (6, 9) 26,255 MW
```

The output is measured with the store read from the local file system. The
Source Cooperative URL is provisional and untested.

- Without the virtual chunk container, the open fails with "you need to
  authorize the virtual chunk container".
- `xarray:open_kwargs` sets `decode_coords="all"`, which makes the
  `grid_mapping` variable a coordinate. rioxarray then finds the CRS. Without
  it, `rio.crs` is `None` (measured).
- `chunks={}` needs `dask`, which a plain read does not.
- Each chunk covers one scan by 250 × 250 pixels. A time series at one pixel
  reads one chunk per scan.

## Quirks

- **Scaled values decode to floats.** With the default decoding, a variable
  with `scale_factor` and `add_offset` decodes to float64, and fill values
  become NaN. A decoded value is never below that variable's `add_offset`.
  Open with `mask_and_scale=False` to get NOAA's stored integers.
- **Some nodata values are inside the number range.** Some `bands` nodata
  values are negative numbers in a float or signed integer range. A sum that
  does not mask them includes them, so exclude values at or below zero before
  a sum of fire radiative power, as the recipe does.
- **A fill value can mean a missing variable.** When a file has no array for a
  pixel variable, the build adds an array with no chunk references for that
  scan, so every read returns the fill value. When a file has no per-scan
  value, the build stores the variable's fill value for that scan.
- **Gaps along `time`.** NOAA's bucket can have no file for a scan, and the cube
  then has no time step for it. Do not assume a fixed 5-minute spacing. A line
  plot joins the two sides of a gap, which hides the gap.
- **Time is mid-scan.** `time` comes from the time value in each NOAA file and
  falls between the start and end stamps in the file name. When a file's time
  value is not usable, `time` is the midpoint of those stamps.
- **Reprocessing stops a read.** Each chunk read sends `If-Unmodified-Since`
  with the time the reference was written. NOAA's bucket answers `412` for a
  file modified after that time (measured), and Icechunk stops the read. It
  does not compare bytes, so a re-upload of identical bytes also stops the
  read. The error is:

  ```text
  the checksum of the object owning the virtual chunk has changed
  ```

## Coordinate reference system

The CRS is the GOES-18 geostationary projection, sweep axis `x`, in
`proj:wkt2`. It has no EPSG code, so `proj:code` is null. What follows from it:

- `x` and `y` are scan angles in radians, not metres and not degrees. The CRS
  is in metres, which are the scan angle times the `perspective_point_height`
  of the `grid_mapping` variable.
- `proj:transform`, and `spatial:transform` in the store, are in metres. Use
  them to convert a longitude and latitude to a pixel, as the recipe does.
  With them and `proj:wkt2`, `pyproj` places the corner and centre pixels
  within 0.001 m of NOAA's published fixed-grid equations (measured).
- rioxarray computes `rio.transform()` from `x` and `y`, so its transform is in
  radians (measured). Do not combine it with the metre CRS.
- A pixel is not a fixed ground size. It is about 2.0 km by 2.1 km at the
  south edge of the sector below the satellite, and about 4.5 km by 7.5 km at
  the northern corners (measured with `pyproj` from the transform). A pixel
  count is not an area. NOAA's per-pixel fire area is in its own pixel
  variable.
- The collection `bbox` crosses the antimeridian. A longitude filter that
  assumes west is less than east excludes the whole sector.
- Web maps need a reprojection to EPSG:3857 with PROJ's geostationary
  projection, `+proj=geos +sweep=x`.

## Schema meaning

- The fire mask gives each pixel one code. Fire pixels are codes 10 to 15 and
  30 to 35 (from its `flag_meanings` attribute). The other codes mark no fire,
  cloud, water, block-out zones and processing failures. The catalog
  [README](../README.md#fire-mask-codes) tabulates them.
- In the data quality flag, 0 marks a good fire pixel and 1 marks good
  fire-free land. Codes 2 to 5 mark invalid pixels (from its `flag_meanings` attribute).
- Fire temperature, radiative power and area exist only "for valid fire pixels
  that satisfy specific criteria" (NOAA's `summary` attribute). Elsewhere they
  hold the nodata value.
- The per-scan summary values are NOAA's own counts and statistics for each
  scan. They are not computed from the cube.

## Related collections and provenance

The catalog has one collection, so nothing joins across collections. The
collection mirrors NOAA's `ABI-L2-FDCC` product in the `noaa-goes18` bucket,
which NOAA and NESDIS produce. `goes-fdc build` in the
[source repository](https://github.com/mmidzik/goes-fdc-catalog) builds the
store from NOAA's file headers and copies no pixel data.

## Structure

Assets and structural links resolve relative to the object that carries them.
Catalogs here have no `self` link, so a client tracks its own location. The
data assets use absolute `https` hrefs built from the public base URL.
