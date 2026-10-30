import numpy as np
import pyproj
import pytest
from zarr_cm import license, proj, spatial, stac

from goes_virtual import grid

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


def test_a_collection_link_added_later_matches_one_built_in():
    url = "https://data.example.org/goes-fdc/goes-18-fdcc/collection.json"
    later = grid.add_collection_link(grid.root_attributes(PROJECTION, X, Y), url)
    built_in = grid.root_attributes(PROJECTION, X, Y, url)
    by_name = lambda attrs: sorted(attrs["zarr_conventions"], key=lambda c: c["name"])  # noqa: E731
    assert by_name(later) == by_name(built_in)
    assert {k: v for k, v in later.items() if k != "zarr_conventions"} == {
        k: v for k, v in built_in.items() if k != "zarr_conventions"
    }


def test_grid_facts_need_the_conventions():
    attrs = grid.root_attributes(PROJECTION, X, Y, None)
    assert set(grid.grid_facts(attrs)) == set(grid.GRID_KEYS)
    with pytest.raises(KeyError, match="proj:wkt2"):
        grid.grid_facts({"goes_fdc:signature": "{}"})


# The Palisades fire area, west, south, east, north in degrees.
PALISADES = (-118.7, 34.0, -118.4, 34.2)


def test_crop_window_covers_the_box_on_whole_source_chunks(cube_at):
    from conftest import CHUNK, SIZE

    cube = cube_at("2025-01-08T03:05")
    window = grid.crop_window(cube, PALISADES)
    for axis in ("x", "y"):
        assert window[axis].start % CHUNK == 0
        assert window[axis].stop % CHUNK == 0 or window[axis].stop == SIZE
        assert window[axis].stop - window[axis].start <= 2 * CHUNK

    # The pixel centres in the window bracket the box on both axes.
    h = PROJECTION["perspective_point_height"]
    lon, lat = np.meshgrid([PALISADES[0], PALISADES[2]], [PALISADES[1], PALISADES[3]])
    x_m, y_m = pyproj.Transformer.from_crs(
        "EPSG:4326", grid.cube_crs(cube), always_xy=True
    ).transform(lon.ravel(), lat.ravel())
    xs = cube["x"].values[window["x"]] * h
    ys = cube["y"].values[window["y"]] * h
    assert xs.min() <= x_m.min() and xs.max() >= x_m.max()
    assert ys.min() <= y_m.min() and ys.max() >= y_m.max()


def test_crop_rewrites_the_spatial_attributes(cube_at):
    cube = cube_at("2025-01-08T03:05")
    cropped = grid.crop(cube, PALISADES)
    x, y = cropped["x"].values, cropped["y"].values
    assert cropped.attrs["spatial:shape"] == [y.size, x.size]
    assert cropped.attrs["spatial:transform"] == grid.transform(PROJECTION, x, y)
    assert cropped.attrs["proj:wkt2"] == cube.attrs["proj:wkt2"]
    assert cropped["Power"].shape == (1, y.size, x.size)
    assert "goes_imager_projection" in cropped.variables
    spatial.validate(cropped.attrs)


def test_a_box_off_the_disk_is_refused(cube_at):
    with pytest.raises(ValueError, match="Earth disk"):
        grid.crop_window(cube_at("2025-01-08T03:05"), (10.0, 40.0, 11.0, 41.0))


def test_edges_are_the_outer_pixel_edges():
    h = PROJECTION["perspective_point_height"]
    west, south, east, north = grid.edges_m(PROJECTION, X, Y)
    assert west == pytest.approx(X[0] * h - STEP * h / 2)
    assert east == pytest.approx(X[-1] * h + STEP * h / 2)
    assert north == pytest.approx(Y[0] * h + STEP * h / 2)
    assert south == pytest.approx(Y[-1] * h - STEP * h / 2)
