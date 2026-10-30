"""A virtual GOES-18 full-disk cube with chunk references and no network access."""

import numpy as np
import pytest
import xarray as xr
from virtualizarr.manifests import ChunkManifest, ManifestArray
from virtualizarr.manifests.utils import create_v3_array_metadata

from goes_virtual import grid

# The CF attributes of goes_imager_projection in a GOES-18 file.
PROJECTION = {
    "grid_mapping_name": "geostationary",
    "perspective_point_height": 35786023.0,
    "semi_major_axis": 6378137.0,
    "semi_minor_axis": 6356752.31414,
    "inverse_flattening": 298.2572221,
    "latitude_of_projection_origin": 0.0,
    "longitude_of_projection_origin": -137.0,
    "sweep_angle_axis": "x",
}
# The FDCF grid: 5424 pixels of 56 microradians, in chunks of 226.
SIZE, CHUNK, STEP = 5424, 226, 5.6e-5
X = -0.151844 + STEP * np.arange(SIZE)
Y = 0.151844 - STEP * np.arange(SIZE)
PREFIX = "https://noaa-goes18.s3.amazonaws.com/"


def make_cube(t: str, transform_shift: float = 0.0) -> xr.Dataset:
    meta = create_v3_array_metadata(
        shape=(1, SIZE, SIZE),
        data_type=np.dtype("float32"),
        chunk_shape=(1, CHUNK, CHUNK),
        fill_value=np.nan,
    )
    n = SIZE // CHUNK
    entries = {
        f"0.{i}.{j}": {"path": f"{PREFIX}f.nc", "offset": (i * n + j) * 8, "length": 8}
        for i in range(n)
        for j in range(n)
    }
    power = ManifestArray(metadata=meta, chunkmanifest=ChunkManifest(entries=entries))
    cube = xr.Dataset(
        {
            "Power": (
                ("time", "y", "x"),
                power,
                {"units": "MW", "grid_mapping": "goes_imager_projection"},
            ),
            "goes_imager_projection": ((), np.int32(-2147483647), PROJECTION),
        },
        coords={"time": [np.datetime64(t, "ns")], "x": X, "y": Y},
    )
    cube.attrs = grid.root_attributes(PROJECTION, X + transform_shift, Y)
    return cube


@pytest.fixture
def cube_at():
    return make_cube
