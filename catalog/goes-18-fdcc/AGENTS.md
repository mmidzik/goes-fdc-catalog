# AGENTS.md — GOES-18 ABI L2 FDCC (virtual Zarr)

Guidance for AI agents and automated clients working with this collection.

This file states no facts of its own. Each line points to the source that holds
the fact. Read the source, not a copy of it.

## Read in this order

1. [`collection.json`](collection.json). `cube:variables` names every variable,
   with its dimensions, unit and description. `cube:dimensions` and `extent`
   give the time range. The `icechunk` asset gives the data type and nodata
   value of each pixel variable in `bands`, and the open arguments in
   `xarray:open_kwargs`.
2. [`README.md` § Access](README.md#access). The tested read recipe and the
   open arguments.
3. [`README.md` § Traps](README.md#traps). The reads that give a wrong answer
   with no error. Read this section before you compute anything.
4. [`README.md` § Store layout](README.md#store-layout) and
   [§ Source files](README.md#source-files). The arrays, the root attributes
   and NOAA's files.
5. The [catalog README](../README.md). The fire mask and quality codes, the time
   of a scan, the gaps, the license and the provenance.
