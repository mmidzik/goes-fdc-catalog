"""Open GOES FDC netCDF files as virtual datasets and stack them along time."""
from __future__ import annotations

import json
import logging
from concurrent.futures import ThreadPoolExecutor

import numpy as np
import xarray as xr
from obstore.store import HTTPStore
from virtualizarr import open_virtual_dataset
from virtualizarr.manifests import ChunkManifest, ManifestArray
from virtualizarr.parsers import HDFParser
from virtualizarr.registry import ObjectStoreRegistry

from . import grid
from .keys import BUCKETS, Scan

VARIABLES = ["Mask", "DQF", "Power", "Temp", "Area"]
KEEP_COORDS = {"time", "x", "y"}

# NOAA's per-scan summary values. The cube keeps them as `time` variables, so
# each scan's own counts and statistics stay with the scan.
SCAN_SCALARS = [
    "total_number_of_pixels_with_fires_detected",
    "total_number_of_pixels_with_fire_temperature",
    "total_number_of_pixels_with_fire_area",
    "total_number_of_pixels_with_fire_radiative_power",
    "fire_temperature_outlier_pixel_count",
    "fire_area_outlier_pixel_count",
    "fire_radiative_power_outlier_pixel_count",
    *(f"{stat}_fire_{quantity}"
      for quantity in ("temperature", "area", "radiative_power")
      for stat in ("minimum", "maximum", "mean", "standard_deviation")),
    "percent_uncorrectable_GRB_errors",
    "percent_uncorrectable_L0_errors",
]
PROJECTION = "goes_imager_projection"

# Each array's CF attributes come from the first scan of a cube. These ones hold
# that scan's own summary values, so they are wrong for every other scan.
PER_SCAN_ATTR_PREFIX = "percent_"

log = logging.getLogger(__name__)


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


def encoding_facts(metadata, attrs: dict) -> dict:
    """The encoding of one array, from its Zarr metadata and its CF attributes."""
    return {
        "chunks": list(metadata.chunk_grid.chunk_shape)[-2:],
        "dtype": str(metadata.data_type),
        "fill_value": str(metadata.fill_value),
        "codecs": [c.to_dict() for c in metadata.codecs],
        "scale_factor": _plain(attrs.get("scale_factor")),
        "add_offset": _plain(attrs.get("add_offset")),
        "units": _plain(attrs.get("units")),
    }


def signature(root_attrs: dict, arrays: dict) -> dict:
    """The grid and encoding facts that every scan in one cube must share.

    A virtual cube inherits the grid and encoding of the files it references,
    and NOAA changes these over the life of a satellite. The facts come from
    standard metadata only: the `proj` and `spatial` root attributes, and each
    array's Zarr metadata and CF scaling. `arrays` maps a variable name to its
    (metadata, attrs) pair.
    """
    sig = {"grid": grid.grid_facts(root_attrs)}
    for name, (metadata, attrs) in arrays.items():
        sig[name] = encoding_facts(metadata, attrs)
    return json.loads(json.dumps(sig, sort_keys=True))


def dataset_signature(ds: xr.Dataset) -> dict:
    """The signature of a virtual dataset, over the pixel variables it has."""
    arrays = {v: (ds[v].data.metadata, ds[v].attrs) for v in VARIABLES if v in ds}
    return signature(ds.attrs, arrays)


def check_signature(expected: dict, found: dict, where: str) -> None:
    """Raise EncodingMismatch naming each fact that differs.

    A variable that only one side has is not a mismatch. The build fills a
    missing variable with fill values instead.
    """
    keys = sorted(k for k in set(expected) & set(found))
    diff = [k for k in keys if expected[k] != found[k]]
    if "grid" not in found or "grid" not in expected:
        diff.append("grid")
    if diff:
        raise EncodingMismatch(
            f"{where}: grid or encoding differs from the cube in {', '.join(diff)}. "
            "These scans belong in a separate cube."
        )


def base_url(satellite: str) -> str:
    return f"https://{BUCKETS[satellite]}.s3.amazonaws.com"


def midpoint(scan: Scan) -> np.datetime64:
    """The middle of the scan, from the start and end stamps in the file name."""
    mid = scan.start + (scan.end - scan.start) / 2
    return np.datetime64(mid.replace(tzinfo=None), "ns")


def scan_time(scan: Scan, t) -> np.datetime64:
    """The file's mid-scan `t`, or the file-name midpoint when `t` is not usable.

    Some files carry the fill value -999 in `t`, with valid pixels. Decoded, that
    is 2000-01-01T11:43:21, outside the scan's own start and end stamps. Any `t`
    outside those stamps gets the midpoint.
    """
    lo = np.datetime64(scan.start.replace(tzinfo=None), "ns") - np.timedelta64(1, "m")
    hi = np.datetime64(scan.end.replace(tzinfo=None), "ns") + np.timedelta64(1, "m")
    if t is not None and lo <= t <= hi:
        return t
    log.warning("%s: t is not usable, using the file-name midpoint", scan.key)
    return midpoint(scan)


def is_aborted(scan: Scan) -> bool:
    """True when the start and end stamps in the file name are equal."""
    return scan.start == scan.end


def mask_is_empty(url: str, registry: ObjectStoreRegistry) -> bool:
    """True when every `Mask` pixel of the file is the fill value. Reads the pixels."""
    ds = open_virtual_dataset(
        url, registry=registry, parser=HDFParser(), loadable_variables=["Mask"],
        decode_times=False,
    )
    return bool(ds["Mask"].isnull().all())


def _clean_attrs(var: xr.Variable) -> None:
    """Remove the attributes that do not describe the cube."""
    var.attrs.pop("coordinates", None)
    for key in [k for k in var.attrs if k.startswith(PER_SCAN_ATTR_PREFIX)]:
        del var.attrs[key]


def virtualize_scan(scan: Scan, registry: ObjectStoreRegistry,
                    collection_url: str | None) -> xr.Dataset | None:
    """Read headers only. The result holds byte-range references, no pixels.

    Returns None for an aborted scan whose `Mask` is all fill values.
    """
    url = f"{base_url(scan.satellite)}/{scan.key}"
    if is_aborted(scan) and mask_is_empty(url, registry):
        log.warning("%s: start and end stamps are equal and Mask is empty, skipping", scan.key)
        return None
    # Decode `t` alone. Some files carry the fill value in `time_bounds`, which
    # stops CF time decoding of the whole file.
    ds = open_virtual_dataset(
        url, registry=registry, parser=HDFParser(),
        loadable_variables=["t", "x", "y", PROJECTION, *SCAN_SCALARS], decode_times=False,
    )
    t = scan_time(scan, xr.decode_cf(ds[["t"]])["t"].values)
    present = [v for v in VARIABLES if v in ds]
    for v in sorted(set(VARIABLES) - set(present)):
        log.warning("%s: no %s array, filling it with the fill value", scan.key, v)
    scalars = []
    for v in SCAN_SCALARS:
        if v in ds:
            scalars.append(v)
        else:
            log.warning("%s: no %s value, storing NaN", scan.key, v)
            ds[v] = xr.DataArray(np.float32("nan"))
            scalars.append(v)
    out = ds[present + scalars].drop_vars(["t"], errors="ignore").expand_dims(time=[t])
    out[PROJECTION] = ds[PROJECTION]
    for name in out.variables:
        _clean_attrs(out[name].variable)
    out.attrs = grid.root_attributes(
        ds[PROJECTION].attrs, ds["x"].values, ds["y"].values, collection_url,
    )
    return out


def fill_array(template: xr.DataArray, time: xr.DataArray) -> xr.DataArray:
    """A one-scan array with no chunk references, so every read returns the fill value."""
    meta = template.data.metadata
    empty = ManifestArray(
        metadata=meta, chunkmanifest=ChunkManifest(entries={}, shape=template.data.manifest.shape_chunk_grid),
    )
    return xr.DataArray(empty, dims=template.dims, attrs=dict(template.attrs)).assign_coords(time=time)


def fill_missing(parts: list[xr.Dataset], scans: list[Scan]) -> list[xr.Dataset]:
    """Add a fill-value array for each pixel variable a scan does not have."""
    templates = {v: next((p[v] for p in parts if v in p), None) for v in VARIABLES}
    out = []
    for scan, part in zip(scans, parts):
        for v in VARIABLES:
            if v in part:
                continue
            if templates[v] is None:
                raise ValueError(f"{scan.key}: no scan in this batch has {v}, so it cannot be filled")
            part = part.assign({v: fill_array(templates[v], part["time"])})
        out.append(part)
    return out


def build_cube(scans: list[Scan], workers: int = 16, collection_url: str | None = None) -> xr.Dataset | None:
    """The virtual cube for a batch of scans, or None when no scan is usable."""
    if not scans:
        raise ValueError("no scans to virtualize")
    satellite = scans[0].satellite
    base = base_url(satellite)
    registry = ObjectStoreRegistry({base: HTTPStore.from_url(base)})
    with ThreadPoolExecutor(max_workers=workers) as pool:
        results = list(pool.map(lambda s: virtualize_scan(s, registry, collection_url), scans))
    kept = [(s, p) for s, p in zip(scans, results) if p is not None]
    if not kept:
        return None
    scans, parts = [s for s, _ in kept], [p for _, p in kept]
    first = dataset_signature(parts[0])
    for scan, part in zip(scans, parts):
        check_signature(first, dataset_signature(part), scan.key)
    parts = fill_missing(parts, scans)
    cube = xr.concat(
        parts, dim="time", data_vars="minimal", coords="minimal",
        compat="override", combine_attrs="override",
    )
    # The other coordinates are per-scan scalars (angles, bounds). Keep the cube to
    # its three dimension coordinates.
    return cube.drop_vars([c for c in cube.coords if c not in KEEP_COORDS])
