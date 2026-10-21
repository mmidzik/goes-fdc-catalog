import numpy as np
import pytest

from goes_fdc.virtualize import EncodingMismatch, _plain, check_signature

SIG = {
    "projection": {"longitude_of_projection_origin": -137.0, "sweep_angle_axis": "x"},
    "x": [-0.1, 0.1, 2500],
    "Mask": {"chunks": [250, 250], "dtype": "int16"},
}


def test_matching_signature_passes():
    check_signature(SIG, dict(SIG), "scan")


def test_moved_satellite_is_refused():
    # GOES-18 FDCC sat at -89.5 during checkout (2022/131) and at -137.0 later.
    moved = {**SIG, "projection": {**SIG["projection"], "longitude_of_projection_origin": -89.5}}
    with pytest.raises(EncodingMismatch, match="projection"):
        check_signature(SIG, moved, "scan")


def test_rechunked_variable_is_refused():
    rechunked = {**SIG, "Mask": {"chunks": [500, 500], "dtype": "int16"}}
    with pytest.raises(EncodingMismatch, match="Mask"):
        check_signature(SIG, rechunked, "scan")


def test_plain_makes_numpy_json_safe():
    assert _plain(np.float32(0.5)) == 0.5
    assert _plain(np.array([1, 2], dtype=np.int16)) == [1, 2]
    assert _plain(0.1234567891234) == 0.123456789


def test_scan_time_falls_back_to_the_file_name_midpoint():
    from datetime import datetime, timezone

    from goes_fdc.keys import Scan
    from goes_fdc.virtualize import scan_time

    utc = timezone.utc
    scan = Scan(
        key="k", product="ABI-L2-FDCC", mode="M4", satellite="G18",
        start=datetime(2025, 1, 20, 15, 10, 22, 400000, tzinfo=utc),
        end=datetime(2025, 1, 20, 15, 15, 12, 400000, tzinfo=utc),
        created=datetime(2025, 1, 20, 15, 17, tzinfo=utc),
    )
    good = np.datetime64("2025-01-20T15:12:47", "ns")
    assert scan_time(scan, good) == good
    assert scan_time(scan, None) == np.datetime64("2025-01-20T15:12:47.400", "ns")
    bogus = np.datetime64("1999-12-31T11:43:21", "ns")  # t = -999 s, decoded
    assert scan_time(scan, bogus) == np.datetime64("2025-01-20T15:12:47.400", "ns")
