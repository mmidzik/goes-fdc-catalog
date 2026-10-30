"""Reads NOAA's GOES-18 bucket. Run with `uv run pytest -m live`."""

import io
from datetime import UTC, datetime

import icechunk
import numpy as np
import pytest
import xarray as xr
from obstore.store import HTTPStore

from goes_virtual import cadence, grid, listing, store, virtualize

pytestmark = pytest.mark.live

PALISADES = (-118.7, 34.0, -118.4, 34.2)
PREFIX = "https://noaa-goes18.s3.amazonaws.com/"


def test_two_full_disk_scans_read_back_as_the_raw_file(tmp_path):
    start = datetime(2025, 1, 8, 3, tzinfo=UTC)
    end = datetime(2025, 1, 8, 3, 20, tzinfo=UTC)
    keys = listing.list_scans("G18", "ABI-L2-FDCF", start, end)
    assert len(keys) == 2
    scans = [k.ref() for k in keys]

    cube = virtualize.build_cube(scans, keep=["Power", "Mask"])
    assert cube is not None
    assert cadence.time_step(cube.scan_modes) == "PT10M"
    window = grid.crop_window(cube.dataset, PALISADES)
    site = grid.crop(cube.dataset, PALISADES)

    repo = store.open_repo(icechunk.local_filesystem_storage(str(tmp_path / "repo")), PREFIX)
    store.write(repo, site, "two scans")
    stored = store.open_cube(repo)
    assert stored is not None
    assert set(stored.data_vars) >= {"Power", "Mask", "goes_imager_projection"}
    for when, scan in zip(stored["time"].values, scans, strict=True):
        assert np.datetime64(scan.start.replace(tzinfo=None)) <= when
        assert when <= np.datetime64(scan.end.replace(tzinfo=None))

    raw_bytes = HTTPStore.from_url(PREFIX).get(keys[0].key).bytes()
    with xr.open_dataset(io.BytesIO(bytes(raw_bytes)), engine="h5netcdf") as raw:
        expected = raw["Power"].isel(x=window["x"], y=window["y"]).values
    np.testing.assert_array_equal(stored["Power"].isel(time=0).values, expected)
