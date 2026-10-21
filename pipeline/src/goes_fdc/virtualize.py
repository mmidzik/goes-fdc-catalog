"""Open GOES FDC netCDF files as virtual datasets and stack them along time."""
from __future__ import annotations

import json
from concurrent.futures import ThreadPoolExecutor

import numpy as np
import xarray as xr
from obstore.store import HTTPStore
from virtualizarr import open_virtual_dataset
from virtualizarr.parsers import HDFParser
from virtualizarr.registry import ObjectStoreRegistry

from .keys import BUCKETS, Scan

VARIABLES = ["Mask", "DQF", "Power", "Temp", "Area"]
KEEP_COORDS = {"time", "x", "y"}

# A virtual cube inherits the grid and encoding of the files it references, so
# every scan in one cube must share them. NOAA changes these over a satellite's
# life: the first GOES-18 FDCC files (2022/131) sit at -89.5 degrees with
# orbital_slot GOES-Test, and the later ones at -137.0. The signature holds the
# facts that must match. A scan that differs stops the build.
SIGNATURE_ATTR = "goes_fdc:signature"
PROJECTION_KEYS = [
    "grid_mapping_name", "perspective_point_height", "semi_major_axis", "semi_minor_axis",
    "latitude_of_projection_origin", "longitude_of_projection_origin", "sweep_angle_axis",
]


class EncodingMismatch(ValueError):
    """A scan's grid or encoding differs from the cube it would join."""


def _plain(value):
    """A JSON-safe copy of an attribute value. NumPy scalars and arrays become Python."""
    if isinstance(value, np.ndarray):
        return [_plain(v) for v in value.tolist()]
    if isinstance(value, np.generic):
        return value.item()
    if isinstance(value, float):
        return round(value, 9)
    return value


def _axis(values: np.ndarray) -> list:
    return [round(float(values[0]), 9), round(float(values[-1]), 9), int(values.size)]


def signature(ds: xr.Dataset) -> dict:
    """The grid and encoding facts that every scan in one cube must share."""
    proj = ds["goes_imager_projection"].attrs
    sig = {
        "projection": {k: _plain(proj.get(k)) for k in PROJECTION_KEYS},
        "x": _axis(ds["x"].values),
        "y": _axis(ds["y"].values),
    }
    for v in VARIABLES:
        meta = ds[v].data.metadata
        attrs = ds[v].attrs
        sig[v] = {
            "shape": list(ds[v].shape),
            "chunks": list(meta.chunk_grid.chunk_shape),
            "dtype": str(meta.data_type),
            "fill_value": str(meta.fill_value),
            "codecs": [c.to_dict() for c in meta.codecs],
            "scale_factor": _plain(attrs.get("scale_factor")),
            "add_offset": _plain(attrs.get("add_offset")),
            "units": _plain(attrs.get("units")),
        }
    return json.loads(json.dumps(sig, sort_keys=True))


def check_signature(expected: dict, found: dict, where: str) -> None:
    """Raise EncodingMismatch naming each fact that differs."""
    if expected == found:
        return
    keys = sorted(set(expected) | set(found))
    diff = [k for k in keys if expected.get(k) != found.get(k)]
    raise EncodingMismatch(
        f"{where}: grid or encoding differs from the cube in {', '.join(diff)}. "
        "These scans belong in a separate cube."
    )


def base_url(satellite: str) -> str:
    return f"https://{BUCKETS[satellite]}.s3.amazonaws.com"


def virtualize_scan(scan: Scan, registry: ObjectStoreRegistry) -> xr.Dataset:
    """Read headers only. The result holds byte-range references, no pixels."""
    url = f"{base_url(scan.satellite)}/{scan.key}"
    ds = open_virtual_dataset(
        url, registry=registry, parser=HDFParser(), loadable_variables=["t", "x", "y"]
    )
    sig = signature(ds)
    t = ds["t"].values
    out = ds[VARIABLES].drop_vars(["t"], errors="ignore").expand_dims(time=[t])
    out.attrs = {SIGNATURE_ATTR: json.dumps(sig, sort_keys=True)}
    return out


def build_cube(scans: list[Scan], workers: int = 16) -> xr.Dataset:
    if not scans:
        raise ValueError("no scans to virtualize")
    satellite = scans[0].satellite
    base = base_url(satellite)
    registry = ObjectStoreRegistry({base: HTTPStore.from_url(base)})
    with ThreadPoolExecutor(max_workers=workers) as pool:
        parts = list(pool.map(lambda s: virtualize_scan(s, registry), scans))
    first = json.loads(parts[0].attrs[SIGNATURE_ATTR])
    for scan, part in zip(scans, parts):
        check_signature(first, json.loads(part.attrs[SIGNATURE_ATTR]), scan.key)
    cube = xr.concat(
        parts, dim="time", coords="minimal", compat="override", combine_attrs="override"
    )
    # The other coordinates are per-scan scalars (angles, bounds). Keep the cube to
    # its three dimension coordinates.
    return cube.drop_vars([c for c in cube.coords if c not in KEEP_COORDS])
