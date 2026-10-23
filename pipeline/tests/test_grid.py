import numpy as np
import pyproj
import pytest
from zarr_cm import license, proj, spatial, stac

from goes_fdc import grid

# The CF attributes of goes_imager_projection in a GOES-18 FDCC file.
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
# Pixel centres in radians, as NOAA's add_offset and scale_factor decode them.
STEP = 5.6e-05
X = -0.069972 + STEP * np.arange(2500)
Y = 0.128212 - STEP * np.arange(1500)


def test_transform_is_in_metres_from_the_outer_pixel_edge():
    a, b, c, d, e, f = grid.transform(PROJECTION, X, Y)
    h = PROJECTION["perspective_point_height"]
    assert a == pytest.approx(STEP * h)
    assert e == pytest.approx(-STEP * h)
    assert (b, d) == (0.0, 0.0)
    assert c == pytest.approx(X[0] * h - a / 2)
    assert f == pytest.approx(Y[0] * h - e / 2)


def test_transform_places_pixel_centres_on_the_coordinates():
    a, _, c, _, e, f = grid.transform(PROJECTION, X, Y)
    h = PROJECTION["perspective_point_height"]
    col, row = 1234, 567
    assert c + a * (col + 0.5) == pytest.approx(X[col] * h)
    assert f + e * (row + 0.5) == pytest.approx(Y[row] * h)


def test_crs_is_the_geostationary_projection():
    crs = grid.crs(PROJECTION)
    assert crs.to_epsg() is None
    params = crs.to_cf()
    assert params["grid_mapping_name"] == "geostationary"
    assert params["sweep_angle_axis"] == "x"
    assert params["longitude_of_projection_origin"] == -137.0


def test_root_attributes_carry_four_valid_conventions():
    url = "https://data.example.org/goes-fdc/goes-18-fdcc/collection.json"
    attrs = grid.root_attributes(PROJECTION, X, Y, url)
    names = {c["name"] for c in attrs["zarr_conventions"]}
    assert names == {"proj", "spatial", "stac:", "license"}
    proj.validate(attrs)
    spatial.validate(attrs)
    stac.validate(attrs)
    license.validate(attrs["license"])
    assert attrs["license"] == {"spdx": "CC0-1.0"}
    assert attrs["stac:link"]["href"] == url
    assert attrs["spatial:shape"] == [1500, 2500]
    assert pyproj.CRS.from_wkt(attrs["proj:wkt2"]) == grid.crs(PROJECTION)


def test_root_attributes_pass_the_geozarr_toolkit_checks():
    geozarr_toolkit = pytest.importorskip("geozarr_toolkit")
    attrs = grid.root_attributes(PROJECTION, X, Y, None)
    report = geozarr_toolkit.validate_attrs(attrs)
    assert report and all(errors == [] for errors in report.values()), report


def test_root_attributes_without_a_collection_url_have_no_stac_link():
    attrs = grid.root_attributes(PROJECTION, X, Y, None)
    assert "stac:link" not in attrs
    assert {c["name"] for c in attrs["zarr_conventions"]} == {"proj", "spatial", "license"}


def test_grid_facts_need_the_conventions():
    attrs = grid.root_attributes(PROJECTION, X, Y, None)
    assert set(grid.grid_facts(attrs)) == set(grid.GRID_KEYS)
    with pytest.raises(KeyError, match="proj:wkt2"):
        grid.grid_facts({"goes_fdc:signature": "{}"})
