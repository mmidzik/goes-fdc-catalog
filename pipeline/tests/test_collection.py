import hashlib

from goes_fdc.collection import EXTENSIONS, collection_json, file_props

INFO = {
    "n_scans": 2,
    "start": "2025-01-07T18:02:35Z",
    "end": "2025-01-07T18:07:35Z",
    "shape": [1500, 2500],
    "transform": [2004.0, 0.0, -2504000.0, 0.0, -2004.0, 4588000.0],
    "x": {"extent": [-2503000.0, 2503000.0], "step": 2004.0},
    "y": {"extent": [1584000.0, 4587000.0], "step": -2004.0},
    "variables": {v: {"unit": "1", "dtype": "int16", "nodata": -99, "description": f"{v} description"}
                  for v in ["Mask", "DQF", "Power", "Temp", "Area"]},
    "bbox": [175.6, 14.5, -89.6, 53.5],
    "other_variables": {},
    "gsd": 2000,
    "wkt2": "WKT",
}
FILES = {"thumbnail": {"file:size": 2}}
BASE = "https://data.example.org/p"


def test_file_props(tmp_path):
    f = tmp_path / "x.bin"
    f.write_bytes(b"abc")
    props = file_props(f)
    assert props["file:size"] == 3
    assert props["file:checksum"] == "1220" + hashlib.sha256(b"abc").hexdigest()


def test_collection_is_a_complete_mirror():
    c = collection_json(INFO, BASE, [175.6, 14.5, -89.6, 53.5], FILES)
    assert c["stac_extensions"] == EXTENSIONS
    roles = [p["roles"] for p in c["providers"]]
    assert "producer" in roles[0] and "host" in roles[-1]
    assert c["license"] == "CC0-1.0"
    assert "updated" in c
    rels = {link["rel"] for link in c["links"]}
    assert {"root", "parent", "describedby", "agents", "via", "license"} <= rels
    assert all("title" in link for link in c["links"])


def test_data_assets_use_absolute_https_hrefs():
    c = collection_json(INFO, BASE, [0, 0, 1, 1], FILES)
    assert set(c["assets"]) == {"icechunk", "thumbnail"}
    assert c["assets"]["icechunk"]["href"].startswith(BASE + "/goes-18-fdcc/")
    assert "xarray:open_kwargs" in c["assets"]["icechunk"]
    # icechunk.http_storage appends "/refs/...". A trailing slash makes an empty
    # path segment, and the Source Cooperative proxy rejects it.
    assert c["assets"]["icechunk"]["href"].endswith("/icechunk")
    store_link = next(link for link in c["links"] if link["rel"] == "store")
    assert store_link["href"] == c["assets"]["icechunk"]["href"]
    assert c["assets"]["thumbnail"]["roles"] == ["thumbnail"]


def test_store_asset_follows_the_proposed_zarr_profile():
    c = collection_json(INFO, BASE, [0, 0, 1, 1], FILES)
    asset = c["assets"]["icechunk"]
    assert asset["type"] == "application/vnd.zarr; version=3"
    assert asset["proj:transform"] == INFO["transform"]
    assert asset["proj:wkt2"] == "WKT"
    assert [b["name"] for b in asset["bands"]] == ["Mask", "DQF", "Power", "Temp", "Area"]
    assert asset["bands"][0]["nodata"] == -99
    assert asset["xarray:open_kwargs"]["decode_coords"] == "all"
    store = [link for link in c["links"] if link["rel"] == "store"]
    assert store and store[0]["href"] == asset["href"]


def test_cube_dimensions_are_in_metres_without_repeated_crs():
    dims = collection_json(INFO, BASE, [0, 0, 1, 1], FILES)["cube:dimensions"]
    for axis in ("x", "y"):
        assert dims[axis]["unit"] == "m"
        assert "reference_system" not in dims[axis]
    assert dims["y"]["step"] == -2004.0


def test_centre_extent_spans_the_pixel_centres():
    from goes_fdc.collection import centre_extent

    assert centre_extent(0.0, 10.0, 3) == [5.0, 25.0]
    assert centre_extent(100.0, -10.0, 3) == [75.0, 95.0]


def test_cube_variables_name_every_store_variable():
    info = {**INFO, "other_variables": {
        "maximum_fire_radiative_power": {"dimensions": ["time"], "unit": "MW", "description": "max FRP"},
        "goes_imager_projection": {"dimensions": [], "unit": "", "description": "projection"},
    }}
    variables = collection_json(info, BASE, [0, 0, 1, 1], FILES)["cube:variables"]
    assert variables["maximum_fire_radiative_power"] == {
        "type": "data", "dimensions": ["time"], "unit": "MW", "description": "max FRP"}
    assert variables["goes_imager_projection"]["type"] == "auxiliary"
    assert "unit" not in variables["goes_imager_projection"]


def test_descriptions_and_bbox_come_from_noaa_attributes():
    from goes_fdc.collection import bbox_from, description

    assert description({"long_name": "ABI L2+ Fire-Hot Spot Characterization: Fire Area"}) == "Fire Area"
    assert description({"long_name": "total number of pixels with fires detected"}) == \
        "Total number of pixels with fires detected"
    assert bbox_from({"geospatial_westbound_longitude": 175.62358093, "geospatial_southbound_latitude": 14.57134,
                      "geospatial_eastbound_longitude": -89.6235733, "geospatial_northbound_latitude": 53.50006}) == \
        [175.62358, 14.57134, -89.62357, 53.50006]
    assert bbox_from({"units": "1"}) is None


def test_render_nodata_is_the_render_variable_fill_value():
    info = {**INFO, "variables": {**INFO["variables"], "Power": {**INFO["variables"]["Power"], "nodata": -9}}}
    c = collection_json(info, BASE, [0, 0, 1, 1], FILES)
    assert c["renders"]["frp"]["nodata"] == -9
    assert c["summaries"]["gsd"] == [2000]



def test_description_states_the_demo_dates_from_the_store():
    c = collection_json(INFO, BASE, [0, 0, 1, 1], FILES)
    assert "from 2025-01-07 to 2025-01-07 (UTC)" in c["description"]
    assert "a short part of the GOES-18 record" in c["description"]
    assert c["description"].startswith("A demo for the Palisades and Eaton fires")
