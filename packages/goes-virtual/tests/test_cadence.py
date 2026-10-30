import pytest

from goes_virtual.cadence import time_step


def test_one_mode_gives_its_step():
    assert time_step([("ABI Mode 6", "Full Disk")] * 3) == "PT10M"
    assert time_step([("ABI Mode 6", "CONUS")]) == "PT5M"


def test_several_modes_have_no_step():
    with pytest.raises(ValueError, match="several"):
        time_step([("ABI Mode 3", "Full Disk"), ("ABI Mode 6", "Full Disk")])


def test_an_unknown_mode_has_no_step():
    with pytest.raises(ValueError, match="no known cadence"):
        time_step([(None, "Full Disk")])
