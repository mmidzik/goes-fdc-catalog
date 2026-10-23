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
    "variables": {v: {"unit": "1", "dtype": "int16", "nodata": -99}
                  for v in ["Mask", "DQF", "Power", "Temp", "Area"]},
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
    assert c["assets"]["icechunk"]["href"].endswith("/icechunk/")
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
