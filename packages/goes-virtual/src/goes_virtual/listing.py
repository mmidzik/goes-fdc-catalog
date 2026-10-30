"""List the scans of one ABI product in a time window from a NOAA bucket."""

from __future__ import annotations

import logging
import re
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timedelta

import obstore
from obstore.store import S3Store

from .scan import BUCKETS, ScanKey, parse_key, require_utc

# A mesoscale product names its domain, such as ABI-L2-FDCM1. Its prefix does not.
MESO_RE = re.compile(r"^(?P<prefix>.+M)[12]$")

log = logging.getLogger(__name__)


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
    satellite: str,
    product: str,
    start: datetime,
    end: datetime,
    band: int | None = None,
    workers: int = 24,
) -> list[ScanKey]:
    """List scans whose start time falls in [start, end), sorted by start time.

    ``product`` is the product in the file name, such as ``ABI-L2-FDCC`` or
    ``ABI-L2-FDCM1``. ``band`` selects one channel of a multi-band product.
    The result holds one product and one band. A prefix that holds more
    raises ValueError. One list call goes to each hour prefix. The calls run
    on a thread pool, because a day is 24 round trips to us-east-1.
    """
    require_utc("start", start)
    require_utc("end", end)
    meso = MESO_RE.match(product)
    prefix = meso["prefix"] if meso else product
    store = bucket_store(satellite)

    def wanted(scan: ScanKey) -> bool:
        if meso and scan.product != product:
            return False
        if band is not None and scan.band != band:
            return False
        return start <= scan.start < end

    def one(hour: str) -> list[ScanKey]:
        found = []
        for batch in obstore.list(store, prefix=hour):
            for obj in batch:
                if not obj["path"].endswith(".nc"):
                    continue
                try:
                    scan = parse_key(obj["path"])
                except ValueError:
                    log.warning("%s: not a GOES ABI key, skipping", obj["path"])
                    continue
                if wanted(scan):
                    found.append(scan)
        return found

    with ThreadPoolExecutor(max_workers=workers) as pool:
        parts = pool.map(one, hour_prefixes(prefix, start, end))
    scans = sorted((s for part in parts for s in part), key=lambda s: s.start)
    kinds = sorted({(s.product, s.band) for s in scans}, key=str)
    if len(kinds) > 1:
        raise ValueError(
            f"{prefix} holds several products or bands in this window: {kinds}. "
            "Name the mesoscale domain in product, or pass band."
        )
    return scans
