"""The Icechunk repository that holds a virtual cube."""

from __future__ import annotations

from typing import Any

import icechunk
import numpy as np
import xarray as xr
import zarr
from zarr.errors import GroupNotFoundError

from . import grid
from .virtualize import (
    check_signature,
    check_variables,
    dataset_signature,
    is_pixel_array,
    signature,
    time_variables,
)

BRANCH = "main"

# The first write fixes the time encoding, and every append reuses it. xarray
# otherwise picks the coarsest exact unit for the first batch. One scan on a
# whole minute gets "days", and a later scan 10 minutes on reads back as 10 days.
TIME_ENCODING = {
    "units": "nanoseconds since 1970-01-01",
    "calendar": "proleptic_gregorian",
    "dtype": "int64",
}


def repo_config(
    prefix: str, split_time_steps: int | None
) -> tuple[icechunk.RepositoryConfig, dict[str, Any]]:
    """The repository config and the virtual chunk credentials for scans under ``prefix``.

    NOAA buckets read anonymously over https, so the credential is the
    HttpAccess sentinel. ``split_time_steps`` sets the time steps per manifest.
    Without splitting, every append rewrites the whole manifest of each array,
    so the repository grows with the square of the number of commits. The
    argument has no default. Pass None only for a store with few appends.
    """
    prefix = prefix if prefix.endswith("/") else prefix + "/"
    cfg = icechunk.RepositoryConfig.default()
    cfg.set_virtual_chunk_container(icechunk.VirtualChunkContainer(prefix, icechunk.http_store()))
    if split_time_steps is not None:
        cfg.manifest = icechunk.ManifestConfig(
            splitting=icechunk.ManifestSplittingConfig.from_dict(
                {
                    icechunk.ManifestSplitCondition.AnyArray(): {
                        icechunk.ManifestSplitDimCondition.DimensionName("time"): split_time_steps
                    }
                }
            )
        )
    credentials: dict[str, Any] = icechunk.containers_credentials(
        {prefix: icechunk.Credentials.HttpAccess()}
    )
    return cfg, credentials


def open_repo(
    storage: icechunk.Storage, prefix: str, split_time_steps: int | None
) -> icechunk.Repository:
    """Open the repository in ``storage``, or create it. See repo_config for the split."""
    cfg, credentials = repo_config(prefix, split_time_steps)
    return icechunk.Repository.open_or_create(
        storage, config=cfg, authorize_virtual_chunk_access=credentials
    )


def open_cube(repo: icechunk.Repository, branch: str = BRANCH) -> xr.Dataset | None:
    """The cube on ``branch``, or None when the store has no cube yet.

    Only a missing group means an empty store. Any other error, such as a lost
    connection to S3, stops the caller. Treating it as empty would restart a
    build from its first day and append those scans a second time.
    """
    try:
        ds: xr.Dataset = xr.open_zarr(repo.readonly_session(branch).store, consolidated=False)
    except GroupNotFoundError:
        return None
    return ds


def last_time(repo: icechunk.Repository, branch: str = BRANCH) -> np.datetime64 | None:
    """Latest `time` value in the store, or None when the store is empty."""
    ds = open_cube(repo, branch)
    if ds is None or not ds["time"].size:
        return None
    latest: np.datetime64 = ds["time"].values.max()
    return latest


def root_group(repo: icechunk.Repository, branch: str = BRANCH) -> zarr.Group:
    """The cube's root group on ``branch``, read-only."""
    return zarr.open_group(repo.readonly_session(branch).store, mode="r")


def stored_signature(repo: icechunk.Repository, branch: str = BRANCH) -> dict[str, Any]:
    """The grid and encoding signature of the stored cube, from its standard metadata."""
    group = root_group(repo, branch)
    arrays = {
        name: (arr.metadata, dict(arr.attrs))
        for name, arr in group.arrays()
        if is_pixel_array(getattr(arr.metadata, "dimension_names", None) or ())
    }
    try:
        return signature(dict(group.attrs), arrays)
    except KeyError as exc:
        raise ValueError(
            f"the store has no proj and spatial conventions ({exc.args[0]}). "
            "Rebuild it from an empty store."
        ) from None


def write(
    repo: icechunk.Repository,
    cube: xr.Dataset,
    message: str,
    collection_url: str | None = None,
    branch: str = BRANCH,
) -> str:
    """Commit the cube, or append it along time. Return the snapshot id.

    An append refuses a cube whose signature or variables differ from the
    store. The store links to `collection_url`. Without one, an append keeps
    the link that the store already has.
    """
    stored = open_cube(repo, branch)
    session = repo.writable_session(branch)
    if stored is None:
        cube = cube.copy()
        cube["time"].encoding.update(TIME_ENCODING)
        cube.vz.to_icechunk(session.store)
    else:
        check_signature(stored_signature(repo, branch), dataset_signature(cube), message)
        check_variables(time_variables(stored), time_variables(cube), message)
        cube[sorted(time_variables(cube))].vz.to_icechunk(session.store, append_dim="time")
        collection_url = collection_url or stored.attrs.get("stac:link", {}).get("href")
    # The root attributes are the conventions only. Replace what the writer left.
    attrs = dict(cube.attrs)
    if collection_url:
        attrs = grid.add_collection_link(attrs, collection_url)
    group = zarr.open_group(session.store, mode="r+")
    group.attrs.clear()
    group.attrs.update(attrs)
    snapshot: str = session.commit(message)
    return snapshot
