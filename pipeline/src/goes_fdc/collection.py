"""Write the STAC collection for a built store.

    uv run python -m goes_fdc.collection \\
        --public-base https://data.source.coop/<ACCOUNT>/goes-fdc

Reads extent, grid, variables and projection from the store, so the metadata
cannot drift from the data. The store is built in place under data_dir, so
`tools/upload_data.py` uploads it as it is.
"""
from __future__ import annotations

import argparse
import hashlib
import json
from datetime import datetime, timezone
from pathlib import Path

import numpy as np
import xarray as xr

from . import store, virtualize

PORTOLAN_SCHEMA = "https://schemas.portolan-sdi.org/portolan/v0.2.0/schema.json"
EXTENSIONS = [
    PORTOLAN_SCHEMA,
    "https://stac-extensions.github.io/zarr/v1.1.0/schema.json",
    "https://stac-extensions.github.io/xarray-assets/v1.0.0/schema.json",
    "https://stac-extensions.github.io/datacube/v2.2.0/schema.json",
    "https://stac-extensions.github.io/projection/v2.0.0/schema.json",
    "https://stac-extensions.github.io/render/v2.0.0/schema.json",
    "https://stac-extensions.github.io/file/v2.1.0/schema.json",
]
SATELLITE = "G18"
MEDIA_TYPE = "application/vnd.zarr; version=3"
# The variable the render hint draws, with its display range. Both are choices.
RENDER_VARIABLE = "Power"
COLLECTION = "goes-18-fdcc"


def _iso(t) -> str:
    return np.datetime_as_string(np.datetime64(t, "s"), unit="s") + "Z"


def _fill(value):
    """A fill value as a JSON number: an int when it is integral."""
    value = float(value)
    return int(value) if value.is_integer() else value


def centre_extent(origin: float, step: float, n: int) -> list[float]:
    """The lowest and highest pixel-centre coordinates along one axis."""
    ends = [origin + step / 2, origin + step * (n - 0.5)]
    return [min(ends), max(ends)]


def description(attrs: dict) -> str:
    """A variable's description from its CF `long_name`.

    NOAA prefixes most names with the product title and a colon, for example
    "ABI L2+ Fire-Hot Spot Characterization: Fire Area". The part after the
    last colon names the variable.
    """
    name = str(attrs.get("long_name", "")).rsplit(": ", 1)[-1].strip()
    return name[:1].upper() + name[1:]


def bbox_from(attrs: dict) -> list[float] | None:
    """The ACDD bounding box of NOAA's scene-extent variable, as [W, S, E, N]."""
    keys = ["geospatial_westbound_longitude", "geospatial_southbound_latitude",
            "geospatial_eastbound_longitude", "geospatial_northbound_latitude"]
    if not all(k in attrs for k in keys):
        return None
    return [round(float(np.ravel(attrs[k])[0]), 5) for k in keys]


def inspect_store(repo_path: Path) -> dict:
    """Facts the collection states, all read from the store itself."""
    repo = store.open_repo(repo_path, SATELLITE)
    ds = xr.open_zarr(repo.readonly_session("main").store, consolidated=False, mask_and_scale=False)
    group = store.root_group(repo)
    attrs = dict(group.attrs)
    pixel = sorted(v for v in ds.data_vars if virtualize.is_pixel_array(ds[v].dims))
    a, _, c, _, e, f = attrs["spatial:transform"]
    height, width = attrs["spatial:shape"]
    return {
        "n_scans": int(ds.sizes["time"]),
        "start": _iso(ds.time.values.min()),
        "end": _iso(ds.time.values.max()),
        "shape": [int(height), int(width)],
        "transform": list(attrs["spatial:transform"]),
        "x": {"extent": centre_extent(c, a, width), "step": a},
        "y": {"extent": centre_extent(f, e, height), "step": e},
        "variables": {
            v: {
                "unit": ds[v].attrs.get("units", ""),
                "dtype": str(group[v].dtype),
                "nodata": _fill(group[v].metadata.fill_value),
                "description": description(ds[v].attrs),
            }
            for v in pixel
        },
        # NOAA's per-scan values and the auxiliary scalars. The collection names
        # them, so the agent guides need not.
        "other_variables": {
            v: {
                "dimensions": list(ds[v].dims),
                "unit": ds[v].attrs.get("units", ""),
                "description": description(ds[v].attrs),
            }
            for v in ds.data_vars if v not in pixel
        },
        "bbox": next((b for v in ds.data_vars if not ds[v].dims and (b := bbox_from(ds[v].attrs))), None),
        # NOAA states the grid as 2 km at nadir. The transform step is the exact
        # nadir spacing, about 2,004 m, so gsd is that step to the nearest 100 m.
        "gsd": int(round(abs(a), -2)),
        "wkt2": attrs["proj:wkt2"],
    }


def file_props(path: Path) -> dict:
    """`file:` extension fields: multihash (sha2-256) and size in bytes."""
    data = path.read_bytes()
    return {"file:checksum": "1220" + hashlib.sha256(data).hexdigest(), "file:size": len(data)}


def cube_variables(info: dict) -> dict:
    """`cube:variables`: the pixel variables, then the per-scan and auxiliary ones."""
    out = {
        v: {"type": "data", "dimensions": ["time", "y", "x"], "unit": m["unit"], "description": m["description"]}
        for v, m in info["variables"].items()
    }
    for v, m in info["other_variables"].items():
        entry = {"type": "data" if m["dimensions"] else "auxiliary", "dimensions": m["dimensions"]}
        if m["unit"]:
            entry["unit"] = m["unit"]
        if m["description"]:
            entry["description"] = m["description"]
        out[v] = entry
    return out


def collection_url(public_base: str) -> str:
    """The published collection.json, for the store's `stac:link` attribute."""
    return f"{public_base.rstrip('/')}/{COLLECTION}/collection.json"


def collection_json(info: dict, base: str, bbox: list[float], files: dict[str, dict]) -> dict:
    root = f"{base}/{COLLECTION}"
    cube_props = {
        "proj:code": None,
        "proj:wkt2": info["wkt2"],
        "proj:shape": info["shape"],
        "proj:transform": info["transform"],
    }
    return {
        "type": "Collection",
        "stac_version": "1.1.0",
        "stac_extensions": EXTENSIONS,
        "id": COLLECTION,
        "title": "GOES-18 ABI L2 Fire/Hot Spot Characterization, CONUS (virtual Zarr)",
        "description": (
            "Fire mask, fire radiative power, temperature, area and data quality for the GOES-18 "
            "CONUS scene, about every 5 minutes, as a virtual Zarr cube. The cube holds byte-range "
            "references into NOAA's ABI-L2-FDCC netCDF files in s3://noaa-goes18. No pixel data is "
            "copied. NOAA produces the data. This collection is a mirror."
        ),
        "license": "CC0-1.0",
        "keywords": ["GOES-18", "ABI", "fire", "FDC", "geostationary", "Zarr"],
        "providers": [
            {
                "name": "NOAA NESDIS",
                "roles": ["producer", "licensor"],
                "url": "https://www.goes-r.gov/",
            },
            {
                "name": "Maya Midzik",
                "roles": ["host", "processor"],
                "url": "https://github.com/mmidzik/goes-fdc-catalog",
            },
        ],
        "extent": {
            "spatial": {"bbox": [bbox]},
            "temporal": {"interval": [[info["start"], info["end"]]]},
        },
        "summaries": {"platform": ["GOES-18"], "instruments": ["ABI"], "gsd": [info["gsd"]]},
        "updated": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
        "cube:dimensions": {
            "time": {"type": "temporal", "extent": [info["start"], info["end"]]},
            "y": {"type": "spatial", "axis": "y", "extent": info["y"]["extent"],
                  "step": info["y"]["step"], "unit": "m"},
            "x": {"type": "spatial", "axis": "x", "extent": info["x"]["extent"],
                  "step": info["x"]["step"], "unit": "m"},
        },
        "cube:variables": cube_variables(info),
        "renders": {
            "frp": {
                "title": "Fire radiative power (MW)",
                "assets": ["icechunk"],
                "rescale": [[0, 200]],
                "colormap_name": "inferno",
                "nodata": info["variables"][RENDER_VARIABLE]["nodata"],
            }
        },
        "assets": {
            "icechunk": {
                "href": f"{root}/icechunk/",
                "type": MEDIA_TYPE,
                "title": "Virtual Zarr cube (Icechunk repository)",
                "description": (
                    "Zarr v3 store in an Icechunk repository. Chunks are byte ranges in NOAA netCDF. "
                    "Open it with icechunk and xarray, and authorize the NOAA https prefix as a "
                    "virtual chunk container. See README.md."
                ),
                "roles": ["data"],
                "zarr:zarr_format": 3,
                "zarr:node_type": "group",
                "zarr:consolidated": False,
                # decode_coords="all" makes goes_imager_projection a coordinate, so CF
                # readers such as rioxarray find the CRS through grid_mapping.
                "xarray:open_kwargs": {"engine": "zarr", "consolidated": False, "decode_coords": "all"},
                "bands": [
                    {"name": v, "description": m["description"], "unit": m["unit"],
                     "data_type": m["dtype"], "nodata": m["nodata"]}
                    for v, m in info["variables"].items()
                ],
                **cube_props,
            },
            "thumbnail": {
                "href": "./thumbnail.png",
                "type": "image/png",
                "title": "Fire radiative power, GOES-18 CONUS",
                "roles": ["thumbnail"],
                **files["thumbnail"],
            },
        },
        "links": [
            {"rel": "root", "href": "../catalog.json", "type": "application/json", "title": "GOES ABI Fire/Hot Spot Characterization"},
            {"rel": "parent", "href": "../catalog.json", "type": "application/json", "title": "GOES ABI Fire/Hot Spot Characterization"},
            {"rel": "describedby", "href": "./README.md", "type": "text/markdown", "title": "Collection README"},
            {"rel": "agents", "href": "./AGENTS.md", "type": "text/markdown", "title": "Collection agent guide"},
            {"rel": "via", "href": "https://registry.opendata.aws/noaa-goes/", "type": "text/html",
             "title": "NOAA GOES on the AWS Registry of Open Data"},
            {"rel": "license", "href": "https://creativecommons.org/publicdomain/zero/1.0/legalcode", "type": "text/html",
             "title": "CC0 1.0 Universal Public Domain Dedication"},
            {"rel": "store", "href": f"{root}/icechunk/", "type": MEDIA_TYPE,
             "title": "Icechunk repository with the Zarr store"},
        ],
    }


def main() -> None:
    p = argparse.ArgumentParser(prog="python -m goes_fdc.collection", description=__doc__)
    p.add_argument("--store", default=str(store.DEFAULT_STORE), help="local path or s3://bucket/prefix of the Icechunk repo")
    p.add_argument("--public-base", required=True)
    p.add_argument("--catalog", type=Path, default=Path("catalog"))
    p.add_argument("--bbox", type=float, nargs=4, default=None, metavar=("W", "S", "E", "N"),
                   help="override the bbox the store gives from NOAA's scene-extent variable")
    args = p.parse_args()

    info = inspect_store(args.store)
    bbox = args.bbox or info["bbox"]
    if bbox is None:
        raise SystemExit("the store has no scene-extent variable. Pass --bbox W S E N.")
    out = args.catalog / COLLECTION
    out.mkdir(parents=True, exist_ok=True)

    files = {"thumbnail": file_props(out / "thumbnail.png")}
    doc = collection_json(info, args.public_base.rstrip("/"), bbox, files)
    (out / "collection.json").write_text(json.dumps(doc, indent=2) + "\n")
    print(f"wrote {out / 'collection.json'}: {info['n_scans']} scans, {info['start']} to {info['end']}")


if __name__ == "__main__":
    main()
