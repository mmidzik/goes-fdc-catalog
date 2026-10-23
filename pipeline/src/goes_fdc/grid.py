"""The CRS and the grid of a GOES fixed-grid scan, and the store root attributes.

NOAA stores `x` and `y` as scan angles in radians, as CF defines a geostationary
grid. The CRS is in metres: scan angle times the satellite height. The `proj`
and `spatial` conventions and the STAC projection extension use metres, so the
transform here is in metres, and `x` and `y` in the store stay in radians.
"""
from __future__ import annotations

import numpy as np
import pyproj
from zarr_cm import license as zcm_license
from zarr_cm import proj as zcm_proj
from zarr_cm import spatial as zcm_spatial
from zarr_cm import stac as zcm_stac

LICENSE_SPDX = "CC0-1.0"


def crs(projection_attrs: dict) -> pyproj.CRS:
    """The CRS from the CF attributes of `goes_imager_projection`."""
    return pyproj.CRS.from_cf(dict(projection_attrs))


def transform(projection_attrs: dict, x: np.ndarray, y: np.ndarray) -> list[float]:
    """The affine transform in metres, `[a, b, c, d, e, f]`.

    `x` and `y` are the decoded scan angles of the pixel centres. The origin is
    the outer edge of the first pixel, as the `spatial` convention and the
    STAC projection extension define it. stactools-goes computes the same
    values for Planetary Computer's GOES items.
    """
    height = float(projection_attrs["perspective_point_height"])
    xm = np.asarray(x, dtype="float64") * height
    ym = np.asarray(y, dtype="float64") * height
    dx = (xm[-1] - xm[0]) / (xm.size - 1)
    dy = (ym[-1] - ym[0]) / (ym.size - 1)
    return [float(dx), 0.0, float(xm[0] - dx / 2), 0.0, float(dy), float(ym[0] - dy / 2)]


def root_attributes(projection_attrs: dict, x: np.ndarray, y: np.ndarray,
                    collection_url: str | None) -> dict:
    """Store root attributes: the `proj`, `spatial`, `stac` and `license` conventions."""
    attrs: dict = {}
    attrs = zcm_proj.insert(attrs, zcm_proj.create(wkt2=crs(projection_attrs).to_wkt("WKT2_2019")))
    attrs = zcm_spatial.insert(attrs, zcm_spatial.create(
        dimensions=["y", "x"],
        transform=transform(projection_attrs, x, y),
        shape=[int(np.size(y)), int(np.size(x))],
    ))
    if collection_url:
        attrs = zcm_stac.insert(attrs, zcm_stac.create(link={
            "rel": "collection", "href": collection_url, "type": "application/json",
        }))
    attrs = zcm_license.insert(attrs, zcm_license.create(spdx=LICENSE_SPDX))
    return attrs


GRID_KEYS = ("proj:wkt2", "spatial:dimensions", "spatial:shape", "spatial:transform")


def grid_facts(attrs: dict) -> dict:
    """The CRS and grid facts that every scan in one cube must share."""
    missing = [k for k in GRID_KEYS if k not in attrs]
    if missing:
        raise KeyError(f"missing root attributes {', '.join(missing)}")
    return {k: attrs[k] for k in GRID_KEYS}
