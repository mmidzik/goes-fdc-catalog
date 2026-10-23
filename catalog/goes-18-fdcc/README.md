# Fire/hot spot characterization from GOES-18 (virtual Zarr)

A virtual Zarr cube over 3,996 GOES-18 CONUS Fire/Hot Spot Characterization
scans, 2025-01-07T00:02Z to 2025-01-20T23:57Z. It holds byte-range references
into NOAA's `ABI-L2-FDCC` netCDF files in the public `noaa-goes18` bucket and
copies no pixel data. The variables, the fire mask and quality codes, and the
grid are described in the [catalog README](../README.md).

One asset, `icechunk`, holds the cube as an Icechunk repository. The Icechunk
tag `demo-2025-01` pins this snapshot. Reading it needs `icechunk`, `zarr` and
`xarray`. The Zarr asset is outside the Portolan conformance surface
([portolan-spec#132](https://github.com/portolan-sdi/portolan-spec/issues/132)).

## License

CC0-1.0, from NOAA. See the [catalog README](../README.md#license) for the
source and NOAA's attribution requests.

## Provenance

NOAA and NESDIS produce the data and remain the authoritative source. This
collection mirrors product `ABI-L2-FDCC` in the `noaa-goes18` bucket
(<https://registry.opendata.aws/noaa-goes/>). The `updated` field holds the time
the collection was last built. There is no scheduled sync. The cube keeps any
gaps in NOAA's bucket.

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
    "https://data.source.coop/<ACCOUNT>/goes-fdc/goes-18-fdcc/icechunk"
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
the collection is uploaded. For a worked example that starts from the catalog,
see `examples/palisades-frp.ipynb` in the
[source repository](https://github.com/mmidzik/goes-fdc-catalog).
