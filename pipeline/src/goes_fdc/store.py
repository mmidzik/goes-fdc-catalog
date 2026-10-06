"""Icechunk repo that holds the virtual cube, and the Kerchunk export."""
from __future__ import annotations

from pathlib import Path

import icechunk
import numpy as np
import xarray as xr

from .virtualize import base_url


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


def append(repo: icechunk.Repository, cube: xr.Dataset, message: str) -> str:
    session = repo.writable_session("main")
    if last_time(repo) is None:
        cube.vz.to_icechunk(session.store)
    else:
        cube.vz.to_icechunk(session.store, append_dim="time")
    return session.commit(message)


def export_kerchunk(cube: xr.Dataset, path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    cube.vz.to_kerchunk(str(path), format="parquet")
