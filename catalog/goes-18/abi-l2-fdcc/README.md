# GOES-18 ABI L2 Fire/Hot Spot Characterization, CONUS (virtual Zarr)

Fire mask, fire radiative power, fire temperature, fire area and a data quality
flag for the GOES-18 CONUS scene. The collection is a **virtual Zarr cube**: it
holds byte-range references into NOAA's `ABI-L2-FDCC` netCDF files in the public
`noaa-goes18` bucket and copies no pixel data.

> **Demo.** This collection covers two weeks of full-scene CONUS scans,
> 2025-01-07 to 2025-01-20 UTC. The same pipeline extends the cube in time. The
> Zarr assets are outside the Portolan conformance surface
> ([portolan-spec#132](https://github.com/portolan-sdi/portolan-spec/issues/132)).

## What is here

| | |
|---|---|
| Scans | 3,996, 2025-01-07T00:02Z to 2025-01-20T23:57Z, time axis `time` (UTC, mid-scan) |
| Snapshot | Icechunk tag `demo-2025-01` |
| Grid | 1500 × 2500, ABI geostationary fixed grid, 2 km at nadir |
| Variables | `Mask`, `DQF`, `Power`, `Temp`, `Area` |
| Platform | GOES-18, ABI, CONUS scene |

One asset, `icechunk`, holds the cube. Reading it needs `icechunk`, `zarr` and
`xarray`. The pixel bytes come from NOAA's bucket, not from this catalog.

## License

NOAA produces the data. The collection links NOAA's data policy
(<https://www.nesdisia.noaa.gov/policy.html>, which the Microsoft Planetary
Computer lists as "Public Domain" for GOES-R imagery). No SPDX identifier fits,
so the `license` field is `other`. A final value is an open question.

## Provenance

NOAA and NESDIS produce the data and remain the authoritative source. This
collection is a mirror of the `noaa-goes18` bucket, product `ABI-L2-FDCC`.
Upstream: <https://registry.opendata.aws/noaa-goes/>. The `updated` field holds
the time the collection was last built. There is no scheduled sync.

NOAA's bucket has no FDCC files for GOES-18 from 2025-01-16 11:57Z to 15:02Z,
so the cube has a 3-hour gap there. In the files below, `t` is the fill value
`-999`, and the pixels are valid. Their `time` is the midpoint of the start and end stamps
in the file name:

| File start | `time` |
|---|---|
| 2025-01-10T00:01:17.5Z | 2025-01-10T00:01:17.5 |
| 2025-01-20T15:10:22.4Z | 2025-01-20T15:12:47.4 |
| 2025-01-20T15:15:22.4Z | 2025-01-20T15:17:47.4 |

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
    "https://data.source.coop/<ACCOUNT>/goes-fdc-catalog/goes-18/abi-l2-fdcc/icechunk"
)
repo = icechunk.Repository.open(storage, config=config, authorize_virtual_chunk_access=credentials)
session = repo.readonly_session(tag="demo-2025-01")   # or branch="main" for the latest
ds = xr.open_zarr(session.store, consolidated=False)

power = ds.Power.isel(time=-1).values   # last scan, raw float32, fill value -9
```

The recipe was tested on 2026-10-21 with `icechunk.http_storage` against the
local store served over HTTP, in a clean environment with only `icechunk`,
`zarr` and `xarray`, and with NOAA read live. It opened the tag `demo-2025-01`
and returned the same values as a local read. Without the virtual chunk
container, the read fails with "you need to authorize the virtual chunk
container". The Source Cooperative URL above is provisional and untested until
the collection is uploaded. For a worked example that starts
from the catalog, see `examples/palisades-frp.ipynb` in the
[source repository](https://github.com/mmidzik/goes-fdc-catalog).
