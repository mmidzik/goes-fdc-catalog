import icechunk
import numpy as np
import pytest
import xarray as xr
from conftest import PREFIX

from goes_virtual import store
from goes_virtual.virtualize import EncodingMismatch


def _repo(tmp_path, split=None):
    return store.open_repo(
        icechunk.local_filesystem_storage(str(tmp_path / "icechunk")), PREFIX, split
    )


def test_new_store_is_empty(tmp_path):
    repo = _repo(tmp_path)
    assert store.open_cube(repo) is None
    assert store.last_time(repo) is None


def test_read_errors_are_not_treated_as_empty(tmp_path, monkeypatch):
    # A lost connection must stop a build, not restart it from its first day.
    repo = _repo(tmp_path)

    def lost_connection(*args, **kwargs):
        raise OSError("connection reset")

    monkeypatch.setattr(store.xr, "open_zarr", lost_connection)
    with pytest.raises(OSError):
        store.last_time(repo)


def test_split_is_optional():
    cfg, _ = store.repo_config(PREFIX, None)
    assert cfg.manifest is None or cfg.manifest.splitting is None
    cfg, _ = store.repo_config(PREFIX, 288)
    assert cfg.manifest.splitting is not None


@pytest.mark.parametrize("split", [None, 2])
def test_write_then_append(tmp_path, cube_at, split):
    repo = _repo(tmp_path, split)
    url = "https://data.example.org/goes-fdc/goes-18-fdcc/collection.json"
    store.write(repo, cube_at("2025-01-08T03:05"), "first", collection_url=url)
    store.write(repo, cube_at("2025-01-08T03:15"), "second")

    cube = store.open_cube(repo)
    expected = np.array(["2025-01-08T03:05", "2025-01-08T03:15"], dtype="datetime64[ns]")
    np.testing.assert_array_equal(cube["time"].values, expected)
    assert store.last_time(repo) == np.datetime64("2025-01-08T03:15", "ns")
    assert "goes_imager_projection" in cube.variables
    assert cube["Power"].attrs["grid_mapping"] == "goes_imager_projection"
    # An append keeps the collection link it was not given.
    assert store.root_group(repo).attrs["stac:link"]["href"] == url
    assert set(store.stored_signature(repo)) == {"grid", "Power"}


def test_append_with_another_grid_is_refused(tmp_path, cube_at):
    repo = _repo(tmp_path)
    store.write(repo, cube_at("2025-01-08T03:05"), "first")
    with pytest.raises(EncodingMismatch, match="grid"):
        store.write(repo, cube_at("2025-01-08T03:15", transform_shift=1e-3), "moved")


def test_append_with_another_variable_is_refused(tmp_path, cube_at):
    repo = _repo(tmp_path)
    store.write(repo, cube_at("2025-01-08T03:05"), "first")
    extra = cube_at("2025-01-08T03:15")
    extra["Count"] = xr.DataArray([3.0], dims=["time"])
    with pytest.raises(EncodingMismatch, match="Added: Count"):
        store.write(repo, extra, "extra")
