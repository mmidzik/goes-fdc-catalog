from datetime import datetime, timezone

from goes_fdc.keys import hour_prefixes, parse_key

KEY = (
    "ABI-L2-FDCC/2025/008/03/"
    "OR_ABI-L2-FDCC-M6_G18_s20250080301172_e20250080303545_c20250080304133.nc"
)


def test_parse_key():
    s = parse_key(KEY)
    assert (s.product, s.mode, s.satellite) == ("ABI-L2-FDCC", "M6", "G18")
    assert s.start == datetime(2025, 1, 8, 3, 1, 17, 200000, tzinfo=timezone.utc)
    assert s.end == datetime(2025, 1, 8, 3, 3, 54, 500000, tzinfo=timezone.utc)


def test_hour_prefixes_cross_midnight():
    a = datetime(2025, 1, 7, 23, 30, tzinfo=timezone.utc)
    b = datetime(2025, 1, 8, 1, 0, tzinfo=timezone.utc)
    assert hour_prefixes("ABI-L2-FDCC", a, b) == [
        "ABI-L2-FDCC/2025/007/23/",
        "ABI-L2-FDCC/2025/008/00/",
    ]
