"""NOAA GOES object keys: parse the name grammar and list keys by time window."""
from __future__ import annotations

import re
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone

import obstore
from obstore.store import S3Store

# OR_ABI-L2-FDCC-M6_G18_s20250080301172_e20250080303545_c20250080304133.nc
KEY_RE = re.compile(
    r"^(?P<product>ABI-L2-FDC[FCM]\d?)/\d{4}/\d{3}/\d{2}/"
    r"OR_(?P<name>ABI-L2-FDC[FCM]\d?)-(?P<mode>M\d)_(?P<sat>G\d{2})_"
    r"s(?P<s>\d{14})_e(?P<e>\d{14})_c(?P<c>\d{14})\.nc$"
)
BUCKETS = {"G16": "noaa-goes16", "G17": "noaa-goes17", "G18": "noaa-goes18", "G19": "noaa-goes19"}


@dataclass(frozen=True)
class Scan:
    key: str
    product: str
    mode: str
    satellite: str
    start: datetime
    end: datetime
    created: datetime


def _stamp(s: str) -> datetime:
    """Parse YYYYDDDHHMMSSs (year, day of year, hour, minute, second, tenths)."""
    base = datetime.strptime(s[:11], "%Y%j%H%M").replace(tzinfo=timezone.utc)
    return base + timedelta(seconds=int(s[11:13]) + int(s[13]) / 10)


def parse_key(key: str) -> Scan:
    m = KEY_RE.match(key)
    if not m:
        raise ValueError(f"not a GOES FDC key: {key}")
    return Scan(
        key=key, product=m["name"], mode=m["mode"], satellite=m["sat"],
        start=_stamp(m["s"]), end=_stamp(m["e"]), created=_stamp(m["c"]),
    )


def hour_prefixes(product: str, start: datetime, end: datetime) -> list[str]:
    """One S3 prefix per UTC hour that overlaps [start, end)."""
    t = start.replace(minute=0, second=0, microsecond=0)
    out = []
    while t < end:
        out.append(f"{product}/{t:%Y}/{t:%j}/{t:%H}/")
        t += timedelta(hours=1)
    return out


def bucket_store(satellite: str) -> S3Store:
    return S3Store(BUCKETS[satellite], region="us-east-1", skip_signature=True)


def list_scans(satellite: str, product: str, start: datetime, end: datetime) -> list[Scan]:
    """List scans whose start time falls in [start, end), sorted by start time."""
    store = bucket_store(satellite)
    scans = []
    for prefix in hour_prefixes(product, start, end):
        for batch in obstore.list(store, prefix=prefix):
            for obj in batch:
                if obj["path"].endswith(".nc"):
                    scan = parse_key(obj["path"])
                    if start <= scan.start < end:
                        scans.append(scan)
    return sorted(scans, key=lambda s: s.start)
