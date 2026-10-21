"""Icechunk repo that holds the virtual cube."""
from __future__ import annotations

import json
from pathlib import Path

import icechunk
import numpy as np
import xarray as xr

from .virtualize import SIGNATURE_ATTR, base_url, check_signature

# The store is built in place under data_dir (catalog.publish.yaml), at the
# path its asset href names, so tools/upload_data.py uploads it unchanged.
DEFAULT_STORE = Path("local/publish/goes-18/abi-l2-fdcc/icechunk")


def repo_config(satellite: str) -> tuple[icechunk.RepositoryConfig, dict]:
    """NOAA buckets read anonymously over https, so the credential is the HttpAccess sentinel."""
    base = base_url(satellite) + "/"
    cfg = icechunk.RepositoryConfig.default()
    cfg.set_virtual_chunk_container(icechunk.VirtualChunkContainer(base, icechunk.http_store()))
    return cfg, icechunk.containers_credentials({base: icechunk.Credentials.HttpAccess()})


def open_repo(path: Path, satellite: str) -> icechunk.Repository:
    cfg, cred = repo_config(satellite)
    storage = icechunk.local_filesystem_storage(str(path))
    return icechunk.Repository.open_or_create(
        storage, config=cfg, authorize_virtual_chunk_access=cred
    )


def last_time(repo: icechunk.Repository) -> np.datetime64 | None:
    """Latest `time` value in the store, or None when the store is empty."""
    try:
        ds = xr.open_zarr(repo.readonly_session("main").store, consolidated=False, decode_times=True)
    except Exception:
        return None
    return ds["time"].values.max() if ds["time"].size else None


def stored_signature(repo: icechunk.Repository) -> dict | None:
    """The grid and encoding signature the store was built with, or None when empty."""
    try:
        ds = xr.open_zarr(repo.readonly_session("main").store, consolidated=False)
    except Exception:
        return None
    raw = ds.attrs.get(SIGNATURE_ATTR)
    return json.loads(raw) if raw else None


def append(repo: icechunk.Repository, cube: xr.Dataset, message: str) -> str:
    """Commit the cube, or append it along time. Refuse a cube whose signature differs."""
    session = repo.writable_session("main")
    if last_time(repo) is None:
        cube.vz.to_icechunk(session.store)
    else:
        expected = stored_signature(repo)
        if expected is None:
            raise ValueError(f"the store has no {SIGNATURE_ATTR} attribute, so an append cannot be checked")
        check_signature(expected, json.loads(cube.attrs[SIGNATURE_ATTR]), message)
        cube.vz.to_icechunk(session.store, append_dim="time")
    return session.commit(message)

