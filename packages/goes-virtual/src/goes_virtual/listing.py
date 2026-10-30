"""List the scans of one ABI product in a time window from a NOAA bucket."""

from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timedelta

import obstore
from obstore.store import S3Store

from .scan import BUCKETS, ScanKey, parse_key


def hour_prefixes(product: str, start: datetime, end: datetime) -> list[str]:
    """One S3 prefix per UTC hour that overlaps [start, end)."""
    t = start.replace(minute=0, second=0, microsecond=0)
    out = []
    while t < end:
        out.append(f"{product}/{t:%Y}/{t:%j}/{t:%H}/")
        t += timedelta(hours=1)
    return out


def bucket_store(satellite: str) -> S3Store:
    """The satellite's NOAA bucket, read anonymously."""
    return S3Store(BUCKETS[satellite], region="us-east-1", skip_signature=True)


def list_scans(
    satellite: str, product: str, start: datetime, end: datetime, workers: int = 24
) -> list[ScanKey]:
    """List scans whose start time falls in [start, end), sorted by start time.

    ``product`` is the prefix product, such as ``ABI-L2-FDCC``. One list call
    goes to each hour prefix. The calls run on a thread pool, because a day is
    24 round trips to us-east-1.
    """
    store = bucket_store(satellite)

    def one(prefix: str) -> list[ScanKey]:
        found = []
        for batch in obstore.list(store, prefix=prefix):
            for obj in batch:
                if obj["path"].endswith(".nc"):
                    scan = parse_key(obj["path"])
                    if start <= scan.start < end:
                        found.append(scan)
        return found

    with ThreadPoolExecutor(max_workers=workers) as pool:
        parts = pool.map(one, hour_prefixes(product, start, end))
    return sorted((s for part in parts for s in part), key=lambda s: s.start)
