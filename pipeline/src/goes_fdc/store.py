"""Icechunk repo that holds the virtual cube."""
from __future__ import annotations

import json
from pathlib import Path

import icechunk
import numpy as np
import xarray as xr
from zarr.errors import GroupNotFoundError

from .virtualize import SIGNATURE_ATTR, base_url, check_signature

# The store is built in place under data_dir (catalog.publish.yaml), at the
# path its asset href names, so tools/upload_data.py uploads it unchanged.
DEFAULT_STORE = Path("local/publish/goes-18-fdcc/icechunk")


# Scans per manifest along `time`. Without splitting, every append rewrites the
# whole manifest of each array, so the repository grows with the square of the
# number of commits. A two-week build with 14 daily commits measured this. The
# last snapshot needed 13.3 MB of manifests, and the repository held 100 MB.
# With a split of one day of CONUS scans, a daily append writes only that day's
# manifests, about 80 KB per 24 scans.
SPLIT_SCANS = 288


def repo_config(satellite: str) -> tuple[icechunk.RepositoryConfig, dict]:
    """NOAA buckets read anonymously over https, so the credential is the HttpAccess sentinel."""
    base = base_url(satellite) + "/"
    cfg = icechunk.RepositoryConfig.default()
    cfg.set_virtual_chunk_container(icechunk.VirtualChunkContainer(base, icechunk.http_store()))
    cfg.manifest = icechunk.ManifestConfig(
        splitting=icechunk.ManifestSplittingConfig.from_dict({
            icechunk.ManifestSplitCondition.AnyArray(): {
                icechunk.ManifestSplitDimCondition.DimensionName("time"): SPLIT_SCANS
            }
        })
    )
    return cfg, icechunk.containers_credentials({base: icechunk.Credentials.HttpAccess()})


def storage_for(location: Path | str) -> icechunk.Storage:
    """Icechunk storage for a local path or an ``s3://bucket/prefix`` URI.

    An s3 location reads credentials from the environment. The update workflow
    uses it to append to the published store in place. It is not used for the
    local demo build, and it is not yet tested against Source Cooperative.
    """
    text = str(location)
    if text.startswith("s3://"):
        bucket, _, prefix = text[len("s3://"):].partition("/")
        return icechunk.s3_storage(bucket=bucket, prefix=prefix.strip("/") or None,
                                   region="us-west-2", from_env=True)
    return icechunk.local_filesystem_storage(text)


def open_repo(path: Path | str, satellite: str) -> icechunk.Repository:
    cfg, cred = repo_config(satellite)
    storage = storage_for(path)
    return icechunk.Repository.open_or_create(
        storage, config=cfg, authorize_virtual_chunk_access=cred
    )


def open_cube(repo: icechunk.Repository) -> xr.Dataset | None:
    """The cube on the main branch, or None when the store has no cube yet.

    Only a missing group means an empty store. Any other error, such as a lost
    connection to S3, stops the caller. Treating it as empty would restart a
    build from its first day and append those scans a second time.
    """
    try:
        return xr.open_zarr(repo.readonly_session("main").store, consolidated=False)
    except GroupNotFoundError:
        return None


def last_time(repo: icechunk.Repository) -> np.datetime64 | None:
    """Latest `time` value in the store, or None when the store is empty."""
    ds = open_cube(repo)
    return ds["time"].values.max() if ds is not None and ds["time"].size else None


def stored_signature(ds: xr.Dataset) -> dict:
    """The grid and encoding signature the cube was built with."""
    raw = ds.attrs.get(SIGNATURE_ATTR)
    if not raw:
        raise ValueError(f"the store has no {SIGNATURE_ATTR} attribute, so an append cannot be checked")
    return json.loads(raw)


def append(repo: icechunk.Repository, cube: xr.Dataset, message: str) -> str:
    """Commit the cube, or append it along time. Refuse a cube whose signature differs."""
    stored = open_cube(repo)
    session = repo.writable_session("main")
    if stored is None:
        cube.vz.to_icechunk(session.store)
    else:
        check_signature(stored_signature(stored), json.loads(cube.attrs[SIGNATURE_ATTR]), message)
        cube.vz.to_icechunk(session.store, append_dim="time")
    return session.commit(message)

