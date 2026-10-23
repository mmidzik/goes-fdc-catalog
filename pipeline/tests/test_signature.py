from datetime import datetime, timezone

import numpy as np
import pytest
import xarray as xr
from virtualizarr.manifests import ChunkManifest, ManifestArray
from virtualizarr.manifests.utils import create_v3_array_metadata

from goes_fdc import virtualize
from goes_fdc.keys import Scan
from goes_fdc.virtualize import EncodingMismatch, _plain, check_signature

GRID = {
    "proj:wkt2": "PROJCRS[... -137 ...]",
    "spatial:dimensions": ["y", "x"],
    "spatial:shape": [1500, 2500],
    "spatial:transform": [2004.0, 0.0, -2504.0, 0.0, -2004.0, 4588.0],
}
MASK = {"chunks": [250, 250], "dtype": "int16", "fill_value": "-99", "codecs": [],
        "scale_factor": None, "add_offset": None, "units": "1"}
SIG = {"grid": GRID, "Mask": MASK}

UTC = timezone.utc


def scan(start, end, key="k"):
    return Scan(key=key, product="ABI-L2-FDCC", mode="M6", satellite="G18",
                start=start, end=end, created=end)


def test_matching_signature_passes():
    check_signature(SIG, dict(SIG), "scan")


def test_moved_satellite_is_refused():
    # GOES-18 FDCC sat at -89.5 during checkout (2022/131) and at -137.0 later.
    moved = {**SIG, "grid": {**GRID, "proj:wkt2": "PROJCRS[... -89.5 ...]"}}
    with pytest.raises(EncodingMismatch, match="grid"):
        check_signature(SIG, moved, "scan")


def test_rechunked_variable_is_refused():
    rechunked = {**SIG, "Mask": {**MASK, "chunks": [500, 500]}}
    with pytest.raises(EncodingMismatch, match="Mask"):
        check_signature(SIG, rechunked, "scan")


def test_a_variable_on_one_side_only_is_not_a_mismatch():
    # The build fills a missing variable with fill values instead.
    check_signature(SIG, {"grid": GRID}, "scan")


def test_a_signature_without_a_grid_is_refused():
    with pytest.raises(EncodingMismatch, match="grid"):
        check_signature(SIG, {"Mask": MASK}, "scan")


def test_plain_makes_numpy_json_safe():
    assert _plain(np.float32(0.5)) == 0.5
    assert _plain(np.array([1, 2], dtype=np.int16)) == [1, 2]
    assert _plain(0.1234567891234) == 0.123456789


def test_scan_time_falls_back_to_the_file_name_midpoint():
    s = scan(datetime(2025, 1, 20, 15, 10, 22, 400000, tzinfo=UTC),
             datetime(2025, 1, 20, 15, 15, 12, 400000, tzinfo=UTC))
    good = np.datetime64("2025-01-20T15:12:47", "ns")
    assert virtualize.scan_time(s, good) == good
    assert virtualize.scan_time(s, None) == np.datetime64("2025-01-20T15:12:47.400", "ns")
    bogus = np.datetime64("1999-12-31T11:43:21", "ns")  # t = -999 s, decoded
    assert virtualize.scan_time(s, bogus) == np.datetime64("2025-01-20T15:12:47.400", "ns")


def test_an_aborted_scan_with_an_empty_mask_is_skipped(monkeypatch):
    stamp = datetime(2025, 1, 10, 0, 1, 17, 500000, tzinfo=UTC)
    aborted = scan(stamp, stamp)
    assert virtualize.is_aborted(aborted)
    monkeypatch.setattr(virtualize, "mask_is_empty", lambda url, registry: True)
    assert virtualize.virtualize_scan(aborted, registry=None, collection_url=None) is None


def _virtual(name, t):
    meta = create_v3_array_metadata(
        shape=(1, 500, 500), data_type=np.dtype("int16"), chunk_shape=(1, 250, 250),
        fill_value=-99,
    )
    entries = {f"0.{i}.{j}": {"path": "https://example.org/f.nc", "offset": 0, "length": 8}
               for i in range(2) for j in range(2)}
    arr = ManifestArray(metadata=meta, chunkmanifest=ChunkManifest(entries=entries))
    return xr.Dataset({name: (("time", "y", "x"), arr, {"units": "1"})}, coords={"time": [t]})


def test_a_missing_variable_is_filled_with_fill_values(monkeypatch):
    monkeypatch.setattr(virtualize, "VARIABLES", ["Mask"])
    t0, t1 = np.datetime64("2025-01-08T07:02", "ns"), np.datetime64("2025-01-08T07:07", "ns")
    s = scan(datetime(2025, 1, 8, 7, 1, tzinfo=UTC), datetime(2025, 1, 8, 7, 3, tzinfo=UTC))
    with_mask = _virtual("Mask", t0)
    without = xr.Dataset(coords={"time": [t1]})
    filled = virtualize.fill_missing([with_mask, without], [s, s])
    added = filled[1]["Mask"]
    assert added.shape == (1, 500, 500)
    assert added.attrs == {"units": "1"}
    assert added.data.manifest.dict() == {}
    assert added.data.metadata.fill_value == -99
    assert filled[1]["time"].values[0] == t1
    cube = xr.concat(filled, dim="time")
    assert cube["Mask"].shape == (2, 500, 500)
    assert len(cube["Mask"].data.manifest.dict()) == 4


def test_a_variable_no_scan_has_cannot_be_filled(monkeypatch):
    monkeypatch.setattr(virtualize, "VARIABLES", ["Mask"])
    s = scan(datetime(2025, 1, 8, 7, 1, tzinfo=UTC), datetime(2025, 1, 8, 7, 3, tzinfo=UTC))
    empty = xr.Dataset(coords={"time": [np.datetime64("2025-01-08T07:02", "ns")]})
    with pytest.raises(ValueError, match="Mask"):
        virtualize.fill_missing([empty], [s])
