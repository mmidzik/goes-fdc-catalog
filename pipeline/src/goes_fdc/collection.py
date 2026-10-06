"""Write the STAC collection for a built store, and stage the data tree.

    uv run python -m goes_fdc.collection --store local/smoke/icechunk \\
        --public-base https://data.source.coop/portolan-mirrors/goes-fdc-catalog

Reads extent, grid, variables and projection from the store, so the metadata
cannot drift from the data. Stages the Icechunk repo and a Kerchunk refs file
under the data directory that `tools/upload_data.py` uploads.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import shutil
from datetime import datetime, timedelta, timezone
from pathlib import Path

import numpy as np
import pyproj
import xarray as xr
from obstore.store import HTTPStore
from virtualizarr import open_virtual_dataset
from virtualizarr.parsers import HDFParser
from virtualizarr.registry import ObjectStoreRegistry

from . import keys, store, virtualize

PORTOLAN_SCHEMA = "https://schemas.portolan-sdi.org/portolan/v0.1.1/schema.json"
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
SLUG = "goes-18"
COLLECTION = "abi-l2-fdcc"
PRODUCT = "ABI-L2-FDCC"


def _iso(t) -> str:
    return np.datetime_as_string(np.datetime64(t, "s"), unit="s") + "Z"


def projection_attrs(first_time: np.datetime64) -> dict:
    """The CF projection attributes, read from the header of the scan at `first_time`."""
    t = datetime.fromtimestamp(int(np.datetime64(first_time, "s").astype(int)), timezone.utc)
    hour = t.replace(minute=0, second=0, microsecond=0)
    scans = keys.list_scans(SATELLITE, PRODUCT, hour, hour + timedelta(hours=1))
    scan = next(s for s in scans if s.start <= t <= s.end)
    base = virtualize.base_url(SATELLITE)
    registry = ObjectStoreRegistry({base: HTTPStore.from_url(base)})
    ds = open_virtual_dataset(
        f"{base}/{scan.key}", registry=registry, parser=HDFParser(),
        loadable_variables=["goes_imager_projection"],
    )
    return dict(ds["goes_imager_projection"].attrs)


def inspect_store(repo_path: Path) -> dict:
    """Facts the collection states, all read from the store itself."""
    repo = store.open_repo(repo_path, SATELLITE)
    ds = xr.open_zarr(repo.readonly_session("main").store, consolidated=False, mask_and_scale=False)
    crs = pyproj.CRS.from_cf(projection_attrs(ds.time.values.min()))
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
    root = f"{base}/{SLUG}/{COLLECTION}"
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
        "license": "other",
        "keywords": ["GOES-18", "ABI", "fire", "FDC", "geostationary", "Zarr"],
        "providers": [
            {
                "name": "NOAA NESDIS",
                "roles": ["producer", "licensor"],
                "url": "https://www.goes-r.gov/",
            },
            {
                "name": "mmidzik (personal repository)",
                "roles": ["host", "processor"],
                "url": "https://github.com/mmidzik/goes-fdc-catalog/issues",
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
            "kerchunk": {
                "href": f"{root}/kerchunk/refs.json",
                "type": "application/json",
                "title": "Virtual Zarr cube (Kerchunk references)",
                "description": (
                    "Kerchunk reference file for the same cube. Open it with xarray's kerchunk "
                    "engine, with no Icechunk dependency. Needs kerchunk, fsspec, aiohttp and requests. "
                    "See README.md."
                ),
                "roles": ["data"],
                "zarr:zarr_format": 2,
                "zarr:node_type": "group",
                "xarray:open_kwargs": {"engine": "kerchunk"},
                "xarray:storage_options": {"remote_protocol": "https"},
                **files["kerchunk"],
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
            {"rel": "root", "href": "../../catalog.json", "type": "application/json", "title": "GOES ABI (NOAA GOES-R)"},
            {"rel": "parent", "href": "../catalog.json", "type": "application/json", "title": "GOES-18"},
            {"rel": "describedby", "href": "./README.md", "type": "text/markdown", "title": "Collection README"},
            {"rel": "agents", "href": "./AGENTS.md", "type": "text/markdown", "title": "Collection agent guide"},
            {"rel": "via", "href": "https://registry.opendata.aws/noaa-goes/", "type": "text/html",
             "title": "NOAA GOES on the AWS Registry of Open Data"},
            {"rel": "license", "href": "https://www.nesdisia.noaa.gov/policy.html", "type": "text/html",
             "title": "NOAA NESDIS data policy"},
        ],
    }


def stage(repo_path: Path, data_dir: Path, cube) -> None:
    """Copy the Icechunk repo and write a Kerchunk refs file under the data tree."""
    dest = data_dir / SLUG / COLLECTION
    if (dest / "icechunk").exists():
        shutil.rmtree(dest / "icechunk")
    shutil.copytree(repo_path, dest / "icechunk")
    (dest / "kerchunk").mkdir(parents=True, exist_ok=True)
    cube.vz.to_kerchunk(str(dest / "kerchunk" / "refs.json"), format="json")


def main() -> None:
    p = argparse.ArgumentParser(prog="python -m goes_fdc.collection", description=__doc__)
    p.add_argument("--store", type=Path, required=True, help="local Icechunk repo")
    p.add_argument("--public-base", required=True)
    p.add_argument("--catalog", type=Path, default=Path("catalog"))
    p.add_argument("--data-dir", type=Path, default=Path("staging/goes/data"))
    p.add_argument("--bbox", type=float, nargs=4, default=None,
                   metavar=("W", "S", "E", "N"), help="from the NOAA file's geospatial_lat_lon_extent")
    args = p.parse_args()

    info = inspect_store(args.store)
    bbox = args.bbox or [175.62358, 14.57134, -89.62357, 53.50006]
    out = args.catalog / SLUG / COLLECTION
    out.mkdir(parents=True, exist_ok=True)

    # Rebuild the cube over exactly the scans in the store, for the Kerchunk refs file.
    t0 = datetime.fromisoformat(info["start"].removesuffix("Z")).replace(tzinfo=timezone.utc)
    t1 = datetime.fromisoformat(info["end"].removesuffix("Z")).replace(tzinfo=timezone.utc)
    scans = keys.list_scans(SATELLITE, PRODUCT, t0 - timedelta(minutes=10), t1 + timedelta(minutes=1))
    scans = [s for s in scans if s.end >= t0 and s.start <= t1]
    if len(scans) != info["n_scans"]:
        raise SystemExit(f"store has {info['n_scans']} scans, listing found {len(scans)}")
    stage(args.store, args.data_dir, virtualize.build_cube(scans))
    print(f"staged data under {args.data_dir / SLUG / COLLECTION}")

    files = {
        "kerchunk": file_props(args.data_dir / SLUG / COLLECTION / "kerchunk" / "refs.json"),
        "thumbnail": file_props(out / "thumbnail.png"),
    }
    doc = collection_json(info, args.public_base.rstrip("/"), bbox, files)
    (out / "collection.json").write_text(json.dumps(doc, indent=2) + "\n")
    print(f"wrote {out / 'collection.json'}: {info['n_scans']} scans, {info['start']} to {info['end']}")


if __name__ == "__main__":
    main()
