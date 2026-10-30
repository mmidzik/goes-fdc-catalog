"""Open GOES FDC netCDF files as virtual datasets and stack them along time."""
from __future__ import annotations

import json
import logging
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass

import numpy as np
import xarray as xr
from obstore.store import HTTPStore
from virtualizarr import open_virtual_dataset
from virtualizarr.manifests import ChunkManifest, ManifestArray
from virtualizarr.parsers import HDFParser
from virtualizarr.registry import ObjectStoreRegistry

from . import grid
from .keys import BUCKETS, Scan

KEEP_COORDS = {"time", "x", "y"}
PIXEL_DIMS = ("y", "x")
# The ACDD attribute that marks NOAA's scene-extent variable.
EXTENT_ATTR = "geospatial_westbound_longitude"

# Each array's CF attributes come from the first scan of a cube. These ones hold
# that scan's own summary values, so they are wrong for every other scan.
PER_SCAN_ATTR_PREFIX = "percent_"

log = logging.getLogger(__name__)


class EncodingMismatch(ValueError):
    """A scan's grid or encoding differs from the cube it would join."""


@dataclass(frozen=True)
class Layout:
    """Which NOAA variables the cube keeps, read from a file's own metadata.

    - pixel: the variables on the `y` × `x` grid
    - scalars: per-scan summary values. CF marks each with `cell_methods`,
      which states the statistic NOAA computed over the scan
    - projection: the variable that the pixel variables name in `grid_mapping`
    - extent: NOAA's scene-extent variable, with the ACDD bounding attributes
    """

    pixel: tuple[str, ...]
    scalars: tuple[str, ...]
    projection: str
    extent: str | None

    @property
    def kept(self) -> tuple[str, ...]:
        """The variables along `time` in the cube."""
        return (*self.pixel, *self.scalars)

    @property
    def loadable(self) -> list[str]:
        """The variables read as values. Everything else stays virtual."""
        return ["t", "x", "y", self.projection, *self.scalars, *([self.extent] if self.extent else [])]


def layout(ds: xr.Dataset) -> Layout:
    """The layout of one file, from its dimensions and CF and ACDD attributes."""
    pixel = tuple(sorted(n for n, v in ds.data_vars.items() if v.dims == PIXEL_DIMS))
    if not pixel:
        raise ValueError("the file has no variable on the y and x grid")
    mappings = {ds[n].attrs.get("grid_mapping") for n in pixel}
    if len(mappings) != 1 or None in mappings:
        raise ValueError(f"the pixel variables do not share one grid_mapping: {sorted(map(str, mappings))}")
    scalars = tuple(sorted(n for n, v in ds.variables.items() if v.ndim == 0 and "cell_methods" in v.attrs))
    extents = [n for n, v in ds.variables.items() if v.ndim == 0 and EXTENT_ATTR in v.attrs]
    return Layout(pixel=pixel, scalars=scalars, projection=mappings.pop(),
                  extent=extents[0] if extents else None)


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


def is_pixel_array(dims) -> bool:
    """True for a cube array on the `time` × `y` × `x` grid."""
    return tuple(dims) == ("time", *PIXEL_DIMS)


def dataset_signature(ds: xr.Dataset) -> dict:
    """The signature of a virtual dataset, over the pixel variables it has."""
    arrays = {v: (ds[v].data.metadata, ds[v].attrs) for v in ds.data_vars if is_pixel_array(ds[v].dims)}
    return signature(ds.attrs, arrays)


def check_signature(expected: dict, found: dict, where: str) -> None:
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
    return {v for v in ds.data_vars if "time" in ds[v].dims}


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


def pixels_are_empty(url: str, registry: ObjectStoreRegistry, pixel: tuple[str, ...]) -> bool:
    """True when every pixel of every pixel variable is the fill value. Reads the pixels."""
    ds = open_virtual_dataset(
        url, registry=registry, parser=HDFParser(), loadable_variables=list(pixel),
        decode_times=False,
    )
    return all(bool(ds[v].isnull().all()) for v in pixel if v in ds)


def _clean_attrs(var: xr.Variable) -> None:
    """Remove the attributes that do not describe the cube."""
    var.attrs.pop("coordinates", None)
    for key in [k for k in var.attrs if k.startswith(PER_SCAN_ATTR_PREFIX)]:
        del var.attrs[key]


def url_of(scan: Scan) -> str:
    return f"{base_url(scan.satellite)}/{scan.key}"


def read_layout(scan: Scan, registry: ObjectStoreRegistry) -> Layout:
    """The layout of one scan's file. Reads headers only."""
    ds = open_virtual_dataset(
        url_of(scan), registry=registry, parser=HDFParser(), loadable_variables=[],
        decode_times=False,
    )
    return layout(ds)


def virtualize_scan(scan: Scan, registry: ObjectStoreRegistry, lay: Layout) -> xr.Dataset | None:
    """Read headers only. The result holds byte-range references, no pixels.

    Returns None for an aborted scan whose pixel variables are all fill values.
    """
    url = url_of(scan)
    if is_aborted(scan) and pixels_are_empty(url, registry, lay.pixel):
        log.warning("%s: start and end stamps are equal and every pixel is empty, skipping", scan.key)
        return None
    # Decode `t` alone. Some files carry the fill value in `time_bounds`, which
    # stops CF time decoding of the whole file.
    ds = open_virtual_dataset(
        url, registry=registry, parser=HDFParser(), loadable_variables=lay.loadable,
        decode_times=False,
    )
    t = scan_time(scan, xr.decode_cf(ds[["t"]])["t"].values)
    present = [v for v in lay.kept if v in ds]
    for v in sorted(set(lay.kept) - set(present)):
        log.warning("%s: no %s variable, filling it", scan.key, v)
    out = ds[present].drop_vars(["t"], errors="ignore").expand_dims(time=[t])
    for aux in (lay.projection, lay.extent):
        if aux and aux in ds:
            out[aux] = ds[aux]
    for name in out.variables:
        _clean_attrs(out[name].variable)
    out.attrs = grid.root_attributes(ds[lay.projection].attrs, ds["x"].values, ds["y"].values)
    return out


def fill_like(template: xr.DataArray, time: xr.DataArray) -> xr.DataArray:
    """A one-scan stand-in for a missing variable, in the encoding of `template`.

    A virtual array gets no chunk references, so every read returns the fill
    value. A loaded scalar gets NaN, which its `_FillValue` encodes on write.
    """
    if isinstance(template.data, ManifestArray):
        meta = template.data.metadata
        empty = ManifestArray(
            metadata=meta, chunkmanifest=ChunkManifest(entries={}, shape=template.data.manifest.shape_chunk_grid),
        )
        filled = xr.DataArray(empty, dims=template.dims, attrs=dict(template.attrs))
    else:
        filled = xr.DataArray(np.full(template.shape, np.nan, dtype=template.dtype),
                              dims=template.dims, attrs=dict(template.attrs))
    filled.encoding = dict(template.encoding)
    return filled.assign_coords(time=time)


def fill_missing(parts: list[xr.Dataset], scans: list[Scan], lay: Layout) -> list[xr.Dataset]:
    """Add a stand-in for each variable of the layout that a scan does not have."""
    templates = {v: next((p[v] for p in parts if v in p), None) for v in lay.kept}
    out = []
    for scan, part in zip(scans, parts):
        for v in lay.kept:
            if v in part:
                continue
            if templates[v] is None:
                raise ValueError(f"{scan.key}: no scan in this batch has {v}, so it cannot be filled")
            part = part.assign({v: fill_like(templates[v], part["time"])})
        out.append(part)
    return out


def build_cube(scans: list[Scan], workers: int = 16) -> tuple[list[Scan], xr.Dataset | None]:
    """The scans that the cube holds, and the virtual cube for a batch of scans.

    The function drops an unusable scan. The cube is None when no scan is usable.
    """
    if not scans:
        raise ValueError("no scans to virtualize")
    satellite = scans[0].satellite
    base = base_url(satellite)
    registry = ObjectStoreRegistry({base: HTTPStore.from_url(base)})
    # One file gives the layout for the batch. A scan that lacks a variable of
    # the layout gets a stand-in for it. An aborted scan can be dropped, so the
    # layout comes from the first complete scan when there is one.
    lay = read_layout(next((s for s in scans if not is_aborted(s)), scans[0]), registry)
    with ThreadPoolExecutor(max_workers=workers) as pool:
        results = list(pool.map(lambda s: virtualize_scan(s, registry, lay), scans))
    scans, parts = [s for s, p in zip(scans, results) if p is not None], [p for p in results if p is not None]
    if not parts:
        return [], None
    first = dataset_signature(parts[0])
    for scan, part in zip(scans, parts):
        check_signature(first, dataset_signature(part), scan.key)
    parts = fill_missing(parts, scans, lay)
    cube = xr.concat(
        parts, dim="time", data_vars="minimal", coords="minimal",
        compat="override", combine_attrs="override",
    )
    # The other coordinates are per-scan scalars (angles, bounds). Keep the cube to
    # its three dimension coordinates.
    return scans, cube.drop_vars([c for c in cube.coords if c not in KEEP_COORDS])
