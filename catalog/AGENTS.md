# AGENTS.md — GOES ABI (NOAA GOES-R)

Guidance for AI agents and automated clients working with this catalog.

**One rule survives every edit to this file.** Every claim here is either quoted
from a source or measured from the data. If you cannot point at where a fact
came from, it does not belong in this file. An agent acting on an invented join
key or an invented column name produces a confident wrong answer, and nothing
downstream catches it.

## What this catalog holds

A pilot. No collection is published yet. The planned first collection is
`goes-18/abi-l2-fdcc`. Public root URL, once published:
`https://data.source.coop/portolan-mirrors/goes-fdc-catalog/` (provisional).

## Where the data comes from

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
| `Mask` | 1500 × 2500 | int16 | 250 × 250 | gzip + shuffle | `_FillValue` -99 |
| `DQF` | 1500 × 2500 | uint8 | 250 × 250 | gzip + shuffle | `_FillValue` 255 |
| `Power` | 1500 × 2500 | float32 | 250 × 250 | gzip + shuffle | units MW, `_FillValue` -9 |
| `Temp` | 1500 × 2500 | uint16 | 250 × 250 | gzip + shuffle | units K, `scale_factor` 0.05493667, `add_offset` 400, `_FillValue` 65535 |
| `Area` | 1500 × 2500 | uint16 | 250 × 250 | gzip + shuffle | units m2, `scale_factor` 60.98, `add_offset` 4000, `_FillValue` 65535 |

Each file also holds a scalar `t` (seconds since 2000-01-01 12:00:00) and
`time_bounds`. The `time` axis in the Zarr cube comes from `t`, which falls
between the file's start and end stamps.

## How to read it

Not yet. The first published collection adds one worked query per access
path, each run against the published files.

## Quirks that produce silently wrong answers

- The grid is the ABI geostationary fixed grid (`grid_mapping` is
  `goes_imager_projection`), not latitude and longitude. `x` and `y` are scan
  angles in radians.
- Open the store with scaling off (`mask_and_scale=False`) to get the raw
  integers NOAA wrote. With scaling on, `Temp` and `Area` decode to float64 and
  fill values become NaN.

## Structure

Assets and structural links resolve relative to the object that carries them.
Catalogs here carry no `self` link, so a client tracks its own location.
