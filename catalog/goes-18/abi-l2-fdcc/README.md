# GOES-18 ABI L2 Fire/Hot Spot Characterization, CONUS (virtual Zarr)

Fire mask, fire radiative power, fire temperature, fire area and a data quality
flag for the GOES-18 CONUS scene. The collection is a **virtual Zarr cube**: it
holds byte-range references into NOAA's `ABI-L2-FDCC` netCDF files in the public
`noaa-goes18` bucket and copies no pixel data.

> **Pilot.** This initial collection holds 24 scans, 2025-01-07T18:02Z to
> 19:57Z, the first two hours of the Palisades fire. It is a test of the
> Source Cooperative layout. The Zarr assets are outside the Portolan
> conformance surface
> ([portolan-spec#132](https://github.com/portolan-sdi/portolan-spec/issues/132)).

## What is here

| | |
|---|---|
| Scans | 24, time axis `time` (UTC, the file's mid-scan `t`) |
| Grid | 1500 × 2500, ABI geostationary fixed grid, 2 km at nadir |
| Variables | `Mask`, `DQF`, `Power`, `Temp`, `Area` |
| Platform | GOES-18, ABI, CONUS scene |

Two assets hold the same cube:

| Asset | Reader needs |
|---|---|
| `icechunk` | `icechunk`, `zarr`, `xarray` |
| `kerchunk` | `xarray`, `kerchunk`, `fsspec`, `aiohttp`, `requests` |

Both fetch the pixel bytes from NOAA's bucket, not from this catalog.

## License

NOAA produces the data. The collection links NOAA's data policy
(<https://www.nesdisia.noaa.gov/policy.html>, which the Microsoft Planetary
Computer lists as "Public Domain" for GOES-R imagery). No SPDX identifier fits,
so the `license` field is `other`. A final value is an open question.

## Provenance

NOAA and NESDIS produce the data and remain the authoritative source. This
collection is a mirror of the `noaa-goes18` bucket, product `ABI-L2-FDCC`.
Upstream: <https://registry.opendata.aws/noaa-goes/>. The `updated` field holds
the time the references were last built. There is no scheduled sync yet.

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
    "https://data.source.coop/portolan-mirrors/goes-fdc-catalog/goes-18/abi-l2-fdcc/icechunk"
)
repo = icechunk.Repository.open(storage, config=config, authorize_virtual_chunk_access=credentials)
ds = xr.open_zarr(repo.readonly_session("main").store, consolidated=False)

power = ds.Power.isel(time=-1).values   # last scan, raw float32, fill value -9
```

Or open the Kerchunk references with no Icechunk dependency:

```python
import xarray as xr

ds = xr.open_dataset(
    "https://data.source.coop/portolan-mirrors/goes-fdc-catalog/goes-18/abi-l2-fdcc/kerchunk/refs.json",
    engine="kerchunk",
    storage_options={"remote_protocol": "https"},
)
```

Both recipes were tested against a local copy of this collection served over HTTP
with Range support, with NOAA read live. They read the same 24 scans and the same
`Power` array. The Source Cooperative URLs above are provisional and untested
until the collection is uploaded.
