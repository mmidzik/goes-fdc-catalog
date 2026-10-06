import hashlib

from goes_fdc.collection import EXTENSIONS, collection_json, file_props

INFO = {
    "n_scans": 2,
    "start": "2025-01-07T18:02:35Z",
    "end": "2025-01-07T18:07:35Z",
    "shape": [1500, 2500],
    "x": [-0.07, 0.07],
    "y": [0.04, 0.13],
    "variables": {v: {"unit": "1", "dtype": "int16"} for v in ["Mask", "DQF", "Power", "Temp", "Area"]},
    "wkt2": "WKT",
}
FILES = {"kerchunk": {"file:size": 1}, "thumbnail": {"file:size": 2}}
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
    assert c["license"] == "other"
    assert "updated" in c
    rels = {link["rel"] for link in c["links"]}
    assert {"root", "parent", "describedby", "agents", "via", "license"} <= rels
    assert all("title" in link for link in c["links"])


def test_data_assets_use_absolute_https_hrefs():
    c = collection_json(INFO, BASE, [0, 0, 1, 1], FILES)
    for key in ("icechunk", "kerchunk"):
        assert c["assets"][key]["href"].startswith(BASE + "/goes-18/abi-l2-fdcc/")
        assert "xarray:open_kwargs" in c["assets"][key]
    assert c["assets"]["icechunk"]["href"].endswith("/icechunk/")
    assert c["assets"]["thumbnail"]["roles"] == ["thumbnail"]
