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
