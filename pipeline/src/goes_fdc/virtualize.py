"""Open GOES FDC netCDF files as virtual datasets and stack them along time."""
from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor

import xarray as xr
from obstore.store import HTTPStore
from virtualizarr import open_virtual_dataset
from virtualizarr.parsers import HDFParser
from virtualizarr.registry import ObjectStoreRegistry

from .keys import BUCKETS, Scan

VARIABLES = ["Mask", "DQF", "Power", "Temp", "Area"]
KEEP_COORDS = {"time", "x", "y"}


def base_url(satellite: str) -> str:
    return f"https://{BUCKETS[satellite]}.s3.amazonaws.com"


def virtualize_scan(scan: Scan, registry: ObjectStoreRegistry) -> xr.Dataset:
    """Read headers only. The result holds byte-range references, no pixels."""
    url = f"{base_url(scan.satellite)}/{scan.key}"
    ds = open_virtual_dataset(
        url, registry=registry, parser=HDFParser(), loadable_variables=["t", "x", "y"]
    )
    t = ds["t"].values
    return ds[VARIABLES].drop_vars(["t"], errors="ignore").expand_dims(time=[t])


def build_cube(scans: list[Scan], workers: int = 16) -> xr.Dataset:
    if not scans:
        raise ValueError("no scans to virtualize")
    satellite = scans[0].satellite
    base = base_url(satellite)
    registry = ObjectStoreRegistry({base: HTTPStore.from_url(base)})
    with ThreadPoolExecutor(max_workers=workers) as pool:
        parts = list(pool.map(lambda s: virtualize_scan(s, registry), scans))
    cube = xr.concat(
        parts, dim="time", coords="minimal", compat="override", combine_attrs="drop_conflicts"
    )
    # Kerchunk's parquet writer fails on leftover scalar coordinates.
    return cube.drop_vars([c for c in cube.coords if c not in KEEP_COORDS])
