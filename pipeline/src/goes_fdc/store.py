"""Where the pipeline keeps its cube: the store location, its storage, and its repository.

The cube itself is built and written by the goes-virtual package.
"""
from __future__ import annotations

from pathlib import Path

import icechunk
from goes_virtual import store as cube_store
from goes_virtual.scan import BUCKETS, object_url

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

# The region of the published store's bucket on Source Cooperative.
PUBLISH_REGION = "us-west-2"


def prefix(satellite: str) -> str:
    """The URL prefix of the satellite's NOAA bucket, which the cube's chunks reference."""
    return object_url(BUCKETS[satellite], "")


def storage_for(location: Path | str, region: str = PUBLISH_REGION) -> icechunk.Storage:
    """Icechunk storage for a local path or an ``s3://bucket/prefix`` URI.

    An s3 location reads credentials from the environment. The update workflow
    uses it to append to the published store in place. It is not used for the
    local demo build, and it is not yet tested against Source Cooperative.
    """
    text = str(location)
    if text.startswith("s3://"):
        bucket, _, key_prefix = text[len("s3://"):].partition("/")
        return icechunk.s3_storage(bucket=bucket, prefix=key_prefix.strip("/") or None,
                                   region=region, from_env=True)
    return icechunk.local_filesystem_storage(text)


def open_repo(location: Path | str, satellite: str) -> icechunk.Repository:
    """The pipeline's repository at ``location``, opened or created."""
    return cube_store.open_repo(storage_for(location), prefix(satellite), SPLIT_SCANS)
