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


def inspect_store(repo_path: Path) -> dict:
    """Facts the collection states, all read from the store itself."""
    repo = store.open_repo(repo_path, SATELLITE)
    ds = xr.open_zarr(repo.readonly_session("main").store, consolidated=False, mask_and_scale=False)
    group = store.root_group(repo)
    attrs = dict(group.attrs)
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
            }
            for v in virtualize.VARIABLES
        },
        "wkt2": attrs["proj:wkt2"],
    }


DESCRIPTIONS = {
    "Mask": "Fire mask: fire, non-fire and obstructed-view categories.",
    "DQF": "Data quality flag.",
    "Power": "Fire radiative power.",
    "Temp": "Fire temperature (scaled integer; scale_factor and add_offset are on the array).",
    "Area": "Fire area (scaled integer; scale_factor and add_offset are on the array).",
}


def file_props(path: Path) -> dict:
    """`file:` extension fields: multihash (sha2-256) and size in bytes."""
    data = path.read_bytes()
    return {"file:checksum": "1220" + hashlib.sha256(data).hexdigest(), "file:size": len(data)}


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
        "summaries": {"platform": ["GOES-18"], "instruments": ["ABI"], "gsd": [2000]},
        "updated": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
        "cube:dimensions": {
            "time": {"type": "temporal", "extent": [info["start"], info["end"]]},
            "y": {"type": "spatial", "axis": "y", "extent": info["y"]["extent"],
                  "step": info["y"]["step"], "unit": "m"},
            "x": {"type": "spatial", "axis": "x", "extent": info["x"]["extent"],
                  "step": info["x"]["step"], "unit": "m"},
        },
        "cube:variables": {
            v: {"type": "data", "dimensions": ["time", "y", "x"], "unit": m["unit"],
                "description": DESCRIPTIONS[v]}
            for v, m in info["variables"].items()
        },
        "renders": {
            "frp": {
                "title": "Fire radiative power (MW)",
                "assets": ["icechunk"],
                "rescale": [[0, 200]],
                "colormap_name": "inferno",
                "nodata": -9,
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
                    {"name": v, "description": DESCRIPTIONS[v], "unit": m["unit"],
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
    p.add_argument("--bbox", type=float, nargs=4, default=None,
                   metavar=("W", "S", "E", "N"), help="from the NOAA file's geospatial_lat_lon_extent")
    args = p.parse_args()

    info = inspect_store(args.store)
    bbox = args.bbox or [175.62358, 14.57134, -89.62357, 53.50006]
    out = args.catalog / COLLECTION
    out.mkdir(parents=True, exist_ok=True)

    files = {"thumbnail": file_props(out / "thumbnail.png")}
    doc = collection_json(info, args.public_base.rstrip("/"), bbox, files)
    (out / "collection.json").write_text(json.dumps(doc, indent=2) + "\n")
    print(f"wrote {out / 'collection.json'}: {info['n_scans']} scans, {info['start']} to {info['end']}")


if __name__ == "__main__":
    main()
