"""Build the fire player site: the page and a Zarr store of fire power over California.

The build starts from the public Portolan catalog. It finds the GOES-18 cube
through the STAC metadata, reads the fire radiative power of every scan over
California, and reprojects it to EPSG:4326. It writes the result as a Zarr v3
store with the GeoZarr `proj` and `spatial` conventions, next to the page.

    uv run --group site python site/build.py local/site
"""

import argparse
import shutil
from pathlib import Path

import icechunk
import numpy as np
import pystac
import pyproj
import rioxarray  # noqa: F401  (adds the .rio accessor)
import xarray as xr
import zarr
from affine import Affine
from rasterio.enums import Resampling
from zarr_cm import proj as zcm_proj
from zarr_cm import spatial as zcm_spatial

CATALOG = "https://data.source.coop/mmidzik/goes-fdc/catalog.json"
COLLECTION = "goes-18-fdcc"
# The catalog has no field for the virtual chunk container. The collection README gives it.
NOAA = "https://noaa-goes18.s3.amazonaws.com/"

# California. West, south, east, north in degrees.
BOX = (-124.5, 32.5, -114.0, 42.0)
RESOLUTION = 0.02  # degrees, about the size of one ABI pixel here

# The output grid. Every day of scans goes onto this same grid.
WEST, SOUTH, EAST, NORTH = BOX
SHAPE = (round((NORTH - SOUTH) / RESOLUTION), round((EAST - WEST) / RESOLUTION))
TRANSFORM = Affine(RESOLUTION, 0.0, WEST, 0.0, -RESOLUTION, NORTH)


def open_cube(asset: pystac.Asset) -> xr.Dataset:
    """The cube that the asset points to, with NOAA's bucket authorized for reads."""
    config = icechunk.RepositoryConfig.default()
    config.set_virtual_chunk_container(icechunk.VirtualChunkContainer(NOAA, icechunk.http_store()))
    repo = icechunk.Repository.open(
        icechunk.http_storage(asset.href),
        config=config,
        authorize_virtual_chunk_access=icechunk.containers_credentials(
            {NOAA: icechunk.Credentials.HttpAccess()}
        ),
    )
    kwargs = {k: v for k, v in asset.extra_fields["xarray:open_kwargs"].items() if k != "engine"}
    return xr.open_zarr(repo.readonly_session(branch="main").store, **kwargs)


def fire_power(asset: pystac.Asset) -> xr.DataArray:
    """Fire radiative power in BOX on the cube's own grid, in projected metres. Lazy."""
    grid_crs = pyproj.CRS.from_wkt(asset.extra_fields["proj:wkt2"])
    # x and y are scan angles in radians. The CRS unit is scan angle times satellite height.
    height = grid_crs.to_cf()["perspective_point_height"]
    to_grid = pyproj.Transformer.from_crs("EPSG:4326", grid_crs, always_xy=True)
    xs, ys = to_grid.transform([WEST, EAST, EAST, WEST], [SOUTH, SOUTH, NORTH, NORTH])
    xs, ys = [v / height for v in xs], [v / height for v in ys]
    power = open_cube(asset)["Power"]
    # y runs north to south on the fixed grid, so its slice is reversed.
    power = power.sel(x=slice(min(xs), max(xs)), y=slice(max(ys), min(ys)))
    power = power.reset_coords(drop=True).assign_coords(x=power.x * height, y=power.y * height)
    return power.rio.write_crs(grid_crs)


def to_lonlat(power: xr.DataArray) -> xr.Dataset:
    """Fire pixels on the output grid, plus the total power of each scan."""
    # where() drops the grid_mapping attribute, so write the CRS again.
    power = power.where(power > 0).rio.write_crs(power.rio.crs).rio.write_nodata(float("nan"))
    frp = power.rio.reproject(
        "EPSG:4326", shape=SHAPE, transform=TRANSFORM, resampling=Resampling.nearest
    )
    frp = frp.rename({"x": "lon", "y": "lat"}).drop_vars("spatial_ref")
    frp.attrs = {"long_name": "fire radiative power", "units": "MW"}
    total = power.sum(("y", "x"))
    total.attrs = {"long_name": "total fire radiative power over California", "units": "MW"}
    ds = xr.Dataset({"frp": frp.astype("float32"), "frp_total": total.astype("float32")})
    # The page reads time as whole seconds. The scan times have sub-second parts.
    return ds.assign_coords(time=ds["time"].dt.floor("s"))


def conventions() -> dict:
    """Root attributes for the GeoZarr `proj` and `spatial` conventions."""
    attrs: dict = {}
    attrs = zcm_proj.insert(attrs, zcm_proj.create(code="EPSG:4326"))
    return zcm_spatial.insert(
        attrs,
        zcm_spatial.create(dimensions=["lat", "lon"], shape=list(SHAPE), transform=list(TRANSFORM)[:6]),
    )


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("out", type=Path, help="site directory to write")
    out = parser.parse_args().out
    out.mkdir(parents=True, exist_ok=True)
    for name in ("index.html", "og-preview.png"):
        shutil.copy(Path(__file__).with_name(name), out / name)
    store = out / "fires.zarr"

    collection = pystac.Catalog.from_file(CATALOG).get_child(COLLECTION)
    power = fire_power(collection.assets["icechunk"])
    zarr.config.set({"async.concurrency": 64})

    # One UTC day at a time keeps the memory to one day of scans.
    days = np.unique(power["time"].values.astype("datetime64[D]"))
    for n, day in enumerate(days):
        ds = to_lonlat(power.sel(time=str(day)).load())
        # An append replaces the root attributes, so every day writes them.
        ds.attrs = conventions() | {"source": collection.get_self_href()}
        if n == 0:
            encoding = {
                "time": {"units": "seconds since 1970-01-01", "dtype": "int64"},
                # One scan per chunk, so the page fetches one small file per frame.
                "frp": {"chunks": (1, *SHAPE)},
            }
            ds.to_zarr(store, mode="w", zarr_format=3, consolidated=False, encoding=encoding)
        else:
            ds.to_zarr(store, append_dim="time", consolidated=False)
        print(f"{day}: {ds.sizes['time']} scans", flush=True)
    print(f"wrote {out}, grid {SHAPE[0]} x {SHAPE[1]}")


if __name__ == "__main__":
    main()
