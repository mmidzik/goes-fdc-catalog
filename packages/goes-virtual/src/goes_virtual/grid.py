"""The CRS and the grid of a GOES fixed-grid scan, the store root attributes, and the site crop.

NOAA stores `x` and `y` as scan angles in radians, as CF defines a geostationary
grid. The CRS is in metres: scan angle times the satellite height. The `proj`
and `spatial` conventions and the STAC projection extension use metres, so the
transform here is in metres, and `x` and `y` in the store stay in radians.
"""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any

import numpy as np
import pyproj
import xarray as xr
from pyproj import Transformer
from zarr_cm import license as zcm_license
from zarr_cm import proj as zcm_proj
from zarr_cm import spatial as zcm_spatial
from zarr_cm import stac as zcm_stac

LICENSE_SPDX = "CC0-1.0"
GRID_KEYS = ("proj:wkt2", "spatial:dimensions", "spatial:shape", "spatial:transform")

# West, south, east, north in EPSG:4326 degrees.
Bbox = tuple[float, float, float, float]


def crs(projection_attrs: Mapping[str, Any]) -> pyproj.CRS:
    """The CRS from the CF attributes of the projection variable."""
    return pyproj.CRS.from_cf(dict(projection_attrs))


def transform(projection_attrs: Mapping[str, Any], x: np.ndarray, y: np.ndarray) -> list[float]:
    """The affine transform in metres, `[a, b, c, d, e, f]`.

    `x` and `y` are the decoded scan angles of the pixel centres. The origin is
    the outer edge of the first pixel, as the `spatial` convention and the
    STAC projection extension define it. stactools-goes computes the same
    values for Planetary Computer's GOES items. A grid of one pixel along an
    axis has no step on that axis, so the transform needs two or more.
    """
    height = float(projection_attrs["perspective_point_height"])
    xm = np.asarray(x, dtype="float64") * height
    ym = np.asarray(y, dtype="float64") * height
    if xm.size < 2 or ym.size < 2:
        raise ValueError(
            f"a transform needs 2 or more pixels on each axis, not {ym.size} x {xm.size}"
        )
    dx = (xm[-1] - xm[0]) / (xm.size - 1)
    dy = (ym[-1] - ym[0]) / (ym.size - 1)
    return [float(dx), 0.0, float(xm[0] - dx / 2), 0.0, float(dy), float(ym[0] - dy / 2)]


def add_collection_link(attrs: dict[str, Any], collection_url: str) -> dict[str, Any]:
    """The attributes with the `stac` convention link to the published collection."""
    result: dict[str, Any] = zcm_stac.insert(
        attrs,
        zcm_stac.create(
            link={"rel": "collection", "href": collection_url, "type": "application/json"}
        ),
    )
    return result


def root_attributes(
    projection_attrs: Mapping[str, Any],
    x: np.ndarray,
    y: np.ndarray,
    collection_url: str | None = None,
    license_spdx: str = LICENSE_SPDX,
) -> dict[str, Any]:
    """Store root attributes: the `proj`, `spatial`, `stac` and `license` conventions."""
    attrs: dict[str, Any] = {}
    attrs = zcm_proj.insert(attrs, zcm_proj.create(wkt2=crs(projection_attrs).to_wkt("WKT2_2019")))
    attrs = zcm_spatial.insert(
        attrs,
        zcm_spatial.create(
            dimensions=["y", "x"],
            transform=transform(projection_attrs, x, y),
            shape=[int(np.size(y)), int(np.size(x))],
        ),
    )
    if collection_url:
        attrs = add_collection_link(attrs, collection_url)
    attrs = zcm_license.insert(attrs, zcm_license.create(spdx=license_spdx))
    return attrs


def grid_facts(attrs: Mapping[str, Any]) -> dict[str, Any]:
    """The CRS and grid facts that every scan in one cube must share."""
    missing = [k for k in GRID_KEYS if k not in attrs]
    if missing:
        raise KeyError(f"missing root attributes {', '.join(missing)}")
    return {k: attrs[k] for k in GRID_KEYS}


def projection_name(cube: xr.Dataset) -> str:
    """The variable that the cube's pixel variables name in `grid_mapping`."""
    names = {
        cube[v].attrs.get("grid_mapping") for v in cube.data_vars if cube[v].dims[-2:] == ("y", "x")
    }
    if len(names) != 1 or None in names:
        raise ValueError(
            f"the pixel variables do not share one grid_mapping: {sorted(map(str, names))}"
        )
    name = str(names.pop())
    if name not in cube.variables:
        raise ValueError(f"the grid mapping variable {name} is not in the cube")
    return name


def cube_crs(cube: xr.Dataset) -> pyproj.CRS:
    """The CRS of the cube, from its grid mapping variable."""
    return crs(cube[projection_name(cube)].attrs)


def _source_chunks(cube: xr.Dataset) -> dict[str, int]:
    """Chunk size along `y` and `x` of the source files, as the manifest records it.

    Every pixel variable of a scan shares its grid and chunking, so the first one is read.
    """
    first = next(cube[v] for v in cube.data_vars if cube[v].dims[-2:] == ("y", "x"))
    chunks = dict(zip(map(str, first.dims), first.data.metadata.chunks, strict=True))
    return {"y": int(chunks["y"]), "x": int(chunks["x"])}


def crop_window(cube: xr.Dataset, bbox: Bbox) -> dict[str, slice]:
    """Index slices of the source chunks that cover ``bbox``.

    ``x`` and ``y`` are scan angles in radians. Times the satellite height, they
    are metres on the projection plane. A virtual array can only be cut on chunk
    boundaries, so the window grows to them.
    """
    projection = cube[projection_name(cube)].attrs
    height = float(projection["perspective_point_height"])
    west, south, east, north = bbox
    grid_lon, grid_lat = np.meshgrid(np.linspace(west, east, 5), np.linspace(south, north, 5))
    x_m, y_m = Transformer.from_crs("EPSG:4326", crs(projection), always_xy=True).transform(
        grid_lon.ravel(), grid_lat.ravel()
    )
    if not (np.isfinite(x_m).all() and np.isfinite(y_m).all()):
        raise ValueError(f"bbox {bbox} is not inside the Earth disk seen by this satellite")

    chunks = _source_chunks(cube)
    window = {}
    for axis, low, high in (("x", x_m.min(), x_m.max()), ("y", y_m.min(), y_m.max())):
        angle = cube[axis].values
        inside = np.flatnonzero((angle >= low / height) & (angle <= high / height))
        if inside.size == 0:  # a box smaller than one pixel: take the pixel it sits in
            inside = np.array([np.abs(angle - (low + high) / 2 / height).argmin()])
        size = chunks[axis]
        start = (int(inside.min()) // size) * size
        stop = min(-(-(int(inside.max()) + 1) // size) * size, angle.size)
        window[axis] = slice(start, stop)
    return window


def edges_m(projection_attrs: Mapping[str, Any], x: np.ndarray, y: np.ndarray) -> list[float]:
    """The outer pixel edges of the grid in metres: min x, min y, max x, max y."""
    a, _, c, _, e, f = transform(projection_attrs, x, y)
    xs = (c, c + a * np.size(x))
    ys = (f, f + e * np.size(y))
    return [float(min(xs)), float(min(ys)), float(max(xs)), float(max(ys))]


def check_inside_disk(crs_: pyproj.CRS, edges: list[float]) -> None:
    """Raise ValueError when a corner of ``edges`` lies off the Earth disk.

    A crop must lie inside the projection's valid domain, or a reader cannot place it.
    """
    xs, ys = [edges[0], edges[2]], [edges[1], edges[3]]
    corners_x, corners_y = np.meshgrid(xs, ys)
    lon, lat = Transformer.from_crs(crs_, "EPSG:4326", always_xy=True).transform(
        corners_x.ravel(), corners_y.ravel()
    )
    if not (np.isfinite(lon).all() and np.isfinite(lat).all()):
        raise ValueError(
            "the crop reaches past the Earth disk; use a smaller box or a site nearer the sub-satellite point"
        )


def crop(cube: xr.Dataset, bbox: Bbox) -> xr.Dataset:
    """The cube cut to the whole source chunks that cover ``bbox``.

    The `spatial:shape` and `spatial:transform` root attributes describe the
    cropped grid. The other root attributes stay as they are.
    """
    window = crop_window(cube, bbox)
    cropped = cube.isel(x=window["x"], y=window["y"])
    projection = cropped[projection_name(cropped)].attrs
    x, y = cropped["x"].values, cropped["y"].values
    check_inside_disk(crs(projection), edges_m(projection, x, y))
    attrs = dict(cube.attrs)
    attrs["spatial:shape"] = [int(y.size), int(x.size)]
    attrs["spatial:transform"] = transform(projection, x, y)
    cropped.attrs = attrs
    return cropped
