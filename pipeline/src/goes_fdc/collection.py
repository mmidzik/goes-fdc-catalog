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
import pyproj
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
COLLECTION = "goes-18-fdcc"


def _iso(t) -> str:
    return np.datetime_as_string(np.datetime64(t, "s"), unit="s") + "Z"


def inspect_store(repo_path: Path) -> dict:
    """Facts the collection states, all read from the store itself."""
    repo = store.open_repo(repo_path, SATELLITE)
    ds = xr.open_zarr(repo.readonly_session("main").store, consolidated=False, mask_and_scale=False)
    # Every scan in the cube shares one projection, recorded in the signature.
    crs = pyproj.CRS.from_cf(store.stored_signature(ds)["projection"])
    return {
        "n_scans": int(ds.sizes["time"]),
        "start": _iso(ds.time.values.min()),
        "end": _iso(ds.time.values.max()),
        "shape": [int(ds.sizes["y"]), int(ds.sizes["x"])],
        "x": [float(ds.x.values.min()), float(ds.x.values.max())],
        "y": [float(ds.y.values.min()), float(ds.y.values.max())],
        "variables": {
            v: {"unit": ds[v].attrs.get("units", ""), "dtype": str(ds[v].dtype)} for v in virtualize.VARIABLES
        },
        "wkt2": crs.to_wkt("WKT2_2019"),
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
            "y": {"type": "spatial", "axis": "y", "extent": info["y"], "unit": "rad",
                  "reference_system": info["wkt2"]},
            "x": {"type": "spatial", "axis": "x", "extent": info["x"], "unit": "rad",
                  "reference_system": info["wkt2"]},
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
                "type": "application/vnd+zarr",
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
                "xarray:open_kwargs": {"engine": "zarr", "consolidated": False},
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
