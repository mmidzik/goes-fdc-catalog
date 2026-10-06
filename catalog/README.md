# GOES ABI (NOAA GOES-R)

Virtual Zarr views over NOAA's GOES-R Advanced Baseline Imager (ABI) files.
The catalog holds references and metadata. The pixel data stays in NOAA's
public `noaa-goes*` buckets.

## What is here

This catalog is a pilot and holds no published collection yet. The first
collection is `abi-l2-fdcc` under `goes-18`: the ABI Level 2 Fire/Hot Spot
Characterization product for CONUS, from GOES-18. It is one 1500 × 2500 grid
per scan, about every 5 minutes. The pilot window is the Palisades fire, 2025-01-07
to 2025-01-31. The catalog later grows to the full GOES-18 record and to other
satellites, sectors, and products.

The Zarr assets are outside the Portolan conformance surface. The Portolan
specification defers Zarr support until real Zarr datasets have been tested in
catalogs ([portolan-spec#132](https://github.com/portolan-sdi/portolan-spec/issues/132)).
This catalog is one of those test cases.

## License

Not yet decided. NOAA publishes the source data. A license value for the
catalog is an open question in the
[design document](https://github.com/mmidzik/goes-fdc-catalog/blob/main/docs/rfd/0001-goes-fdc-virtual-zarr.md).

## Provenance

NOAA and NESDIS produce the data and remain the authoritative source. This
catalog is a mirror. Upstream: <https://registry.opendata.aws/noaa-goes/>. No
sync runs yet.

## Access

No collection is published yet, so there is no query to run. The first
published collection adds one here, run against the published store.
