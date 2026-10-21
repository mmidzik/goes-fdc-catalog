# Fire/hot spot characterization from the GOES-R imager

Virtual Zarr views of the Fire/Hot Spot Characterization (FDC) product from
NOAA's GOES-R Advanced Baseline Imager (ABI).
The catalog holds references and metadata. The pixel data stays in NOAA's
public `noaa-goes*` buckets.

## What is here

This catalog is a pilot. Publishing to Source Cooperative is TODO, so nothing is
published yet. The one collection is `abi-l2-fdcc` under `goes-18`: the ABI Level 2 Fire/Hot Spot
Characterization product for CONUS, from GOES-18. It is one 1500 × 2500 grid
per scan, about every 5 minutes. The pilot window is the Palisades fire, 2025-01-07
to 2025-01-31. Later versions add the full GOES-18 record and the other GOES-R satellites.
The full disk and mesoscale FDC sectors come after that. The catalog covers the
FDC product only.

The Zarr assets are outside the Portolan conformance surface. The Portolan
specification defers Zarr support until real Zarr datasets have been tested in
catalogs ([portolan-spec#132](https://github.com/portolan-sdi/portolan-spec/issues/132)).
This catalog is one of those test cases.

## License

Not yet decided. NOAA publishes the source data. A license value for the
catalog is an open question in the
[design document](https://github.com/mmidzik/goes-fdc-catalog/blob/main/docs/architecture.md).

## Provenance

NOAA and NESDIS produce the data and remain the authoritative source. This
catalog is a mirror. Upstream: <https://registry.opendata.aws/noaa-goes/>. No
sync runs yet.

## Access

The catalog is not published yet. Each collection documents its own access. Start with
[goes-18/abi-l2-fdcc](./goes-18/abi-l2-fdcc/README.md).
