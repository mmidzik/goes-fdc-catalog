from datetime import UTC, datetime

import pytest

from goes_virtual.listing import hour_prefixes
from goes_virtual.scan import parse_key

FDCC = (
    "ABI-L2-FDCC/2025/008/03/"
    "OR_ABI-L2-FDCC-M6_G18_s20250080301172_e20250080303545_c20250080304133.nc"
)


def test_parse_fire_key():
    s = parse_key(FDCC)
    assert (s.product, s.mode, s.band, s.satellite) == ("ABI-L2-FDCC", "M6", None, "G18")
    assert s.start == datetime(2025, 1, 8, 3, 1, 17, 200000, tzinfo=UTC)
    assert s.end == datetime(2025, 1, 8, 3, 3, 54, 500000, tzinfo=UTC)
    assert s.created == datetime(2025, 1, 8, 3, 4, 13, 300000, tzinfo=UTC)


@pytest.mark.parametrize(
    ("key", "product", "band"),
    [
        (
            "ABI-L2-FDCF/2025/008/03/OR_ABI-L2-FDCF-M6_G18_s20250080300208_e20250080309516_c20250080310089.nc",
            "ABI-L2-FDCF",
            None,
        ),
        (
            "ABI-L2-CMIPF/2025/008/03/OR_ABI-L2-CMIPF-M6C13_G18_s20250080300208_e20250080309528_c20250080309590.nc",
            "ABI-L2-CMIPF",
            13,
        ),
        (
            "ABI-L1b-RadC/2025/008/03/OR_ABI-L1b-RadC-M6C02_G18_s20250080301172_e20250080303545_c20250080303592.nc",
            "ABI-L1b-RadC",
            2,
        ),
        (
            "ABI-L2-FDCM/2025/008/03/OR_ABI-L2-FDCM1-M6_G18_s20250080300251_e20250080300308_c20250080300370.nc",
            "ABI-L2-FDCM1",
            None,
        ),
        (
            "ABI-L2-MCMIPC/2025/008/03/OR_ABI-L2-MCMIPC-M6_G19_s20250080301172_e20250080303545_c20250080304051.nc",
            "ABI-L2-MCMIPC",
            None,
        ),
    ],
)
def test_parse_other_abi_keys(key, product, band):
    s = parse_key(key)
    assert (s.product, s.band) == (product, band)


@pytest.mark.parametrize(
    "key",
    [
        "GLM-L2-LCFA/2025/008/03/OR_GLM-L2-LCFA_G18_s20250080300000_e20250080300200_c20250080300216.nc",
        "ABI-L2-FDCC/2025/008/03/OR_ABI-L2-FDCF-M6_G18_s20250080301172_e20250080303545_c20250080304133.nc",
        "ABI-L2-FDCC/2025/008/03/readme.txt",
    ],
)
def test_parse_refuses_other_keys(key):
    with pytest.raises(ValueError, match="not a GOES ABI key"):
        parse_key(key)


def test_ref_is_the_public_https_url():
    ref = parse_key(FDCC).ref()
    assert ref.url == f"https://noaa-goes18.s3.amazonaws.com/{FDCC}"
    assert ref.start == parse_key(FDCC).start


def test_hour_prefixes_cross_midnight():
    a = datetime(2025, 1, 7, 23, 30, tzinfo=UTC)
    b = datetime(2025, 1, 8, 1, 0, tzinfo=UTC)
    assert hour_prefixes("ABI-L2-FDCC", a, b) == [
        "ABI-L2-FDCC/2025/007/23/",
        "ABI-L2-FDCC/2025/008/00/",
    ]
