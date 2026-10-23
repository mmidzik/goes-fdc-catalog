import pytest

from goes_fdc import store


def test_new_store_is_empty(tmp_path):
    repo = store.open_repo(tmp_path / "icechunk", "G18")
    assert store.open_cube(repo) is None
    assert store.last_time(repo) is None


def test_read_errors_are_not_treated_as_empty(tmp_path, monkeypatch):
    # A lost connection must stop a build, not restart it from its first day.
    repo = store.open_repo(tmp_path / "icechunk", "G18")

    def lost_connection(*args, **kwargs):
        raise OSError("connection reset")

    monkeypatch.setattr(store.xr, "open_zarr", lost_connection)
    with pytest.raises(OSError):
        store.last_time(repo)


def test_storage_for_s3_splits_bucket_and_prefix(monkeypatch):
    calls = {}
    monkeypatch.setattr(store.icechunk, "s3_storage", lambda **kw: calls.update(kw))
    store.storage_for("s3://us-west-2.opendata.source.coop/acct/goes-fdc-catalog/icechunk/")
    assert calls["bucket"] == "us-west-2.opendata.source.coop"
    assert calls["prefix"] == "acct/goes-fdc-catalog/icechunk"
