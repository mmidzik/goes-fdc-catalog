# AGENTS.md — GOES fire/hot spot characterization

The collection guide with the file layout, the read recipe and the traps is
[goes-18-fdcc/AGENTS.md](goes-18-fdcc/AGENTS.md). Humans want
[README.md](README.md) for the variables and codes, and
[goes-18-fdcc/README.md](goes-18-fdcc/README.md) for the recipe.

Guidance for AI agents and automated clients working with this catalog.

**One rule survives every edit to this file.** Every claim here is either quoted
from a source or measured from the data. If you cannot point at where a fact
came from, it does not belong in this file.

## What this catalog holds

One collection so far. The catalog is not published yet. Public root, provisional:
`https://data.source.coop/<ACCOUNT>/goes-fdc/catalog.json`

| collection | holds |
|---|---|
| [`goes-18-fdcc`](goes-18-fdcc/collection.json) | A virtual Zarr cube of GOES-18 CONUS FDC scans in one Icechunk repository. The time extent is in the collection |

NOAA and NESDIS produce the data and are the authoritative source. This catalog is a **mirror**, and the pixel bytes are in NOAA's `noaa-goes18` bucket.

## Start here

The file layout, the read recipe, the traps, and a measured check value all
live in the collection guide:
[`goes-18-fdcc/AGENTS.md`](goes-18-fdcc/AGENTS.md). Read it
before you open the cube.

Read the variable names from `cube:variables` in each `collection.json`, not
from this file. These traps most often produce a confident wrong answer:

- `x` and `y` are ABI scan angles in radians, not longitude and latitude.
- Some nodata values are negative numbers. A sum that does not mask them
  includes them. Each pixel variable's nodata value is in the asset's `bands`.
- The store opens only after the reader authorizes
  `https://noaa-goes18.s3.amazonaws.com/` as an Icechunk virtual chunk container.

## Join keys

The catalog has one collection, so nothing joins across collections. A scan
is identified by its `time` value, and a pixel by (`time`, `y`, `x`).

## Structure

Assets and structural links resolve relative to the object that carries them.
Catalogs here carry no `self` link, so a client tracks its own location.
