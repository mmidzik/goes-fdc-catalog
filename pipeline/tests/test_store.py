from goes_virtual import store as cube_store

from goes_fdc import store


def test_new_store_is_empty(tmp_path):
    repo = store.open_repo(tmp_path / "icechunk", "G18")
    assert cube_store.open_cube(repo) is None
    assert cube_store.last_time(repo) is None


def test_prefix_is_the_noaa_bucket():
    assert store.prefix("G18") == "https://noaa-goes18.s3.amazonaws.com/"


def test_storage_for_s3_splits_bucket_and_prefix(monkeypatch):
    calls = {}
    monkeypatch.setattr(store.icechunk, "s3_storage", lambda **kw: calls.update(kw))
    store.storage_for("s3://us-west-2.opendata.source.coop/acct/goes-fdc/icechunk/")
    assert calls["bucket"] == "us-west-2.opendata.source.coop"
    assert calls["prefix"] == "acct/goes-fdc/icechunk"
    assert calls["region"] == "us-west-2"
