"""Open ABI netCDF files as virtual datasets and stack them along time."""

from __future__ import annotations

import json
import logging
from collections.abc import Sequence
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass
from typing import Any, cast
from urllib.parse import urlsplit

import numpy as np
import xarray as xr
from obspec_utils.registry import ObjectStoreRegistry
from obstore.store import HTTPStore
from virtualizarr import open_virtual_dataset
from virtualizarr.manifests import ChunkManifest, ManifestArray
from virtualizarr.parsers import HDFParser

from . import grid
from .layout import PIXEL_DIMS, Layout, layout
from .scan import ScanRef

KEEP_COORDS = {"time", "x", "y"}

# Each array's CF attributes come from the first scan of a cube. These ones hold
# that scan's own summary values, so they are wrong for every other scan.
PER_SCAN_ATTR_PREFIX = "percent_"

# A scan's ABI scan mode and scene. They are the file's `timeline_id` and `scene_id`.
ScanMode = tuple[str | None, str | None]

log = logging.getLogger(__name__)


class EncodingMismatch(ValueError):
    """A scan's grid or encoding differs from the cube it would join."""


@dataclass(frozen=True)
class VirtualScan:
    """One scan as a virtual dataset of one time step, with its scan mode."""

    dataset: xr.Dataset
    mode: ScanMode


@dataclass(frozen=True)
class VirtualCube:
    """Scans stacked along `time`. ``scan_modes`` follows the order of `time`."""

    dataset: xr.Dataset
    scan_modes: list[ScanMode]


def _plain(value: Any) -> Any:
    """A JSON-safe copy of an attribute value. NumPy scalars and arrays become Python."""
    if isinstance(value, np.ndarray):
        return [_plain(v) for v in value.tolist()]
    if isinstance(value, np.generic):
        return value.item()
    if isinstance(value, float):
        return round(value, 9)
    return value


def encoding_facts(metadata: Any, attrs: dict[str, Any]) -> dict[str, Any]:
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


def signature(
    root_attrs: dict[str, Any], arrays: dict[str, tuple[Any, dict[str, Any]]]
) -> dict[str, Any]:
    """The grid and encoding facts that every scan in one cube must share.

    A virtual cube inherits the grid and encoding of the files it references,
    and NOAA changes these over the life of a satellite. The facts come from
    standard metadata only: the `proj` and `spatial` root attributes, and each
    array's Zarr metadata and CF scaling. `arrays` maps a variable name to its
    (metadata, attrs) pair.
    """
    sig: dict[str, Any] = {"grid": grid.grid_facts(root_attrs)}
    for name, (metadata, attrs) in arrays.items():
        sig[name] = encoding_facts(metadata, attrs)
    result: dict[str, Any] = json.loads(json.dumps(sig, sort_keys=True))
    return result


def is_pixel_array(dims: Sequence[Any]) -> bool:
    """True for a cube array on the `time` × `y` × `x` grid."""
    return tuple(dims) == ("time", *PIXEL_DIMS)


def dataset_signature(ds: xr.Dataset) -> dict[str, Any]:
    """The signature of a virtual dataset, over the pixel variables it has."""
    arrays = {
        str(v): (ds[v].data.metadata, dict(ds[v].attrs))
        for v in ds.data_vars
        if is_pixel_array(ds[v].dims)
    }
    return signature(dict(ds.attrs), arrays)


def check_signature(expected: dict[str, Any], found: dict[str, Any], where: str) -> None:
    """Raise EncodingMismatch naming each fact that differs.

    A variable that only one side has is not a mismatch. Inside one batch, the
    build fills a missing variable. check_variables refuses it on an append.
    """
    diff = sorted(k for k in set(expected) & set(found) if expected[k] != found[k])
    if diff:
        raise EncodingMismatch(
            f"{where}: grid or encoding differs from the cube in {', '.join(diff)}. "
            "These scans belong in a separate cube."
        )


def time_variables(ds: xr.Dataset) -> set[str]:
    """The data variables along `time`. An append extends each of them."""
    return {str(v) for v in ds.data_vars if "time" in ds[v].dims}


def check_variables(expected: set[str], found: set[str], where: str) -> None:
    """Raise EncodingMismatch when an append adds or drops a variable along `time`.

    An append extends only the arrays the new scans have. A variable on one
    side only gets a length that differs from `time`.
    """
    if expected == found:
        return
    added, dropped = sorted(found - expected), sorted(expected - found)
    raise EncodingMismatch(
        f"{where}: the variables differ from the cube. Added: {', '.join(added) or 'none'}. "
        f"Missing: {', '.join(dropped) or 'none'}."
    )


def _naive_ns(value: Any) -> np.datetime64:
    return np.datetime64(value.replace(tzinfo=None), "ns")


def midpoint(scan: ScanRef) -> np.datetime64:
    """The middle of the scan, from its start and end stamps."""
    return _naive_ns(scan.start + (scan.end - scan.start) / 2)


def scan_time(scan: ScanRef, t: np.datetime64 | None) -> np.datetime64:
    """The file's mid-scan `t`, or the stamp midpoint when `t` is not usable.

    Some files carry the fill value -999 in `t`, with valid pixels. Decoded, that
    is 2000-01-01T11:43:21, outside the scan's own start and end stamps. Any `t`
    more than 1 minute outside those stamps gets the midpoint.
    """
    lo = _naive_ns(scan.start) - np.timedelta64(1, "m")
    hi = _naive_ns(scan.end) + np.timedelta64(1, "m")
    if t is not None and lo <= t <= hi:
        return t
    log.warning("%s: t is not usable, using the file-name midpoint", scan.url)
    return midpoint(scan)


def is_aborted(scan: ScanRef) -> bool:
    """True when the start and end stamps are equal."""
    return scan.start == scan.end


def pixels_are_empty(url: str, registry: ObjectStoreRegistry[Any], pixel: tuple[str, ...]) -> bool:
    """True when every pixel of every pixel variable is the fill value. Reads the pixels."""
    ds = open_virtual_dataset(
        url,
        registry=registry,
        parser=HDFParser(),
        loadable_variables=list(pixel),
        decode_times=False,
    )
    return all(bool(ds[v].isnull().all()) for v in pixel if v in ds)


def _clean_attrs(var: xr.Variable) -> None:
    """Remove the attributes that do not describe the cube."""
    var.attrs.pop("coordinates", None)
    for key in [k for k in var.attrs if str(k).startswith(PER_SCAN_ATTR_PREFIX)]:
        del var.attrs[key]


def registry_for(scans: Sequence[ScanRef]) -> tuple[str, ObjectStoreRegistry[Any]]:
    """The URL origin that every scan shares, and a registry that reads it over https."""
    origins = {"{0.scheme}://{0.netloc}".format(urlsplit(s.url)) for s in scans}
    if len(origins) != 1:
        raise ValueError(f"the scans are on more than one host: {sorted(origins)}")
    (origin,) = origins
    return origin, ObjectStoreRegistry({origin: HTTPStore.from_url(origin)})


def read_layout(scan: ScanRef, registry: ObjectStoreRegistry[Any]) -> Layout:
    """The layout of one scan's file. Reads headers only."""
    ds = open_virtual_dataset(
        scan.url,
        registry=registry,
        parser=HDFParser(),
        loadable_variables=[],
        decode_times=False,
    )
    return layout(ds)


def virtualize_scan(
    scan: ScanRef, registry: ObjectStoreRegistry[Any], lay: Layout
) -> VirtualScan | None:
    """Read headers only. The result holds byte-range references, no pixels.

    Returns None for an aborted scan whose pixel variables are all fill values.
    """
    if is_aborted(scan) and pixels_are_empty(scan.url, registry, lay.pixel):
        log.warning(
            "%s: start and end stamps are equal and every pixel is empty, skipping", scan.url
        )
        return None
    # Decode `t` alone. Some files carry the fill value in `time_bounds`, which
    # stops CF time decoding of the whole file.
    ds = open_virtual_dataset(
        scan.url,
        registry=registry,
        parser=HDFParser(),
        loadable_variables=lay.loadable,
        decode_times=False,
    )
    decoded = cast(np.datetime64, xr.decode_cf(ds[["t"]])["t"].values[()])
    t = scan_time(scan, decoded)
    present = [v for v in lay.kept if v in ds]
    for v in sorted(set(lay.kept) - set(present)):
        log.warning("%s: no %s variable, filling it", scan.url, v)
    out = ds[present].drop_vars(["t"], errors="ignore").expand_dims(time=[t])
    if lay.projection not in ds:
        raise ValueError(f"{scan.url}: no {lay.projection} variable, so the scan has no CRS")
    out[lay.projection] = ds[lay.projection]
    if lay.extent and lay.extent in ds:
        out[lay.extent] = ds[lay.extent]
    for name in out.variables:
        _clean_attrs(out[name].variable)
    mode: ScanMode = (ds.attrs.get("timeline_id"), ds.attrs.get("scene_id"))
    out.attrs = grid.root_attributes(ds[lay.projection].attrs, ds["x"].values, ds["y"].values)
    return VirtualScan(out, mode)


def fill_like(template: xr.DataArray, time: xr.DataArray) -> xr.DataArray:
    """A one-scan stand-in for a missing variable, in the encoding of `template`.

    A virtual array gets no chunk references, so every read returns the fill
    value. A loaded scalar gets NaN, which its `_FillValue` encodes on write.
    """
    if isinstance(template.data, ManifestArray):
        meta = template.data.metadata
        empty = ManifestArray(
            metadata=meta,
            chunkmanifest=ChunkManifest(entries={}, shape=template.data.manifest.shape_chunk_grid),
        )
        filled = xr.DataArray(empty, dims=template.dims, attrs=dict(template.attrs))
    else:
        filled = xr.DataArray(
            np.full(template.shape, np.nan, dtype=template.dtype),
            dims=template.dims,
            attrs=dict(template.attrs),
        )
    filled.encoding = dict(template.encoding)
    return filled.assign_coords(time=time)


def fill_missing(
    parts: list[xr.Dataset], scans: Sequence[ScanRef], lay: Layout
) -> list[xr.Dataset]:
    """Add a stand-in for each variable of the layout that a scan does not have."""
    templates = {v: next((p[v] for p in parts if v in p), None) for v in lay.kept}
    out = []
    for scan, part in zip(scans, parts, strict=True):
        for v in lay.kept:
            if v in part:
                continue
            template = templates[v]
            if template is None:
                raise ValueError(
                    f"{scan.url}: no scan in this batch has {v}, so it cannot be filled"
                )
            part = part.assign({v: fill_like(template, part["time"])})
        out.append(part)
    return out


def build_cube(
    scans: Sequence[ScanRef], keep: Sequence[str] | None = None, workers: int = 16
) -> VirtualCube | None:
    """The virtual cube for a batch of scans, or None when no scan is usable.

    ``keep`` names the pixel and per-scan variables to keep. ``None`` keeps all of them.
    """
    if not scans:
        raise ValueError("no scans to virtualize")
    _, registry = registry_for(scans)
    # One file gives the layout for the batch. A scan that lacks a variable of
    # the layout gets a stand-in for it. An aborted scan can be dropped, so the
    # layout comes from the first complete scan when there is one.
    first_complete = next((s for s in scans if not is_aborted(s)), scans[0])
    lay = read_layout(first_complete, registry).select(keep)
    with ThreadPoolExecutor(max_workers=workers) as pool:
        results = list(pool.map(lambda s: virtualize_scan(s, registry, lay), scans))
    usable = [(s, r) for s, r in zip(scans, results, strict=True) if r is not None]
    if not usable:
        return None
    kept_scans = [s for s, _ in usable]
    parts = [r.dataset for _, r in usable]
    first = dataset_signature(parts[0])
    for scan, part in zip(kept_scans, parts, strict=True):
        check_signature(first, dataset_signature(part), scan.url)
    parts = fill_missing(parts, kept_scans, lay)
    cube = xr.concat(
        parts,
        dim="time",
        data_vars="minimal",
        coords="minimal",
        compat="override",
        combine_attrs="override",
    )
    # The other coordinates are per-scan scalars (angles, bounds). Keep the cube to
    # its three dimension coordinates.
    cube = cube.drop_vars([c for c in cube.coords if c not in KEEP_COORDS])
    return VirtualCube(cube, [r.mode for _, r in usable])
