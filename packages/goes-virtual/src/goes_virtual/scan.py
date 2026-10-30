"""NOAA GOES ABI object keys, and the scan references that virtualization reads."""

from __future__ import annotations

import re
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta

# OR_ABI-L2-FDCC-M6_G18_s20250080301172_e20250080303545_c20250080304133.nc
# OR_ABI-L2-CMIPF-M6C13_G18_s20250080300208_e20250080309516_c20250080309590.nc
# The prefix product has no mesoscale number: ABI-L2-FDCM holds ABI-L2-FDCM1 and ABI-L2-FDCM2.
KEY_RE = re.compile(
    r"^(?P<prefix>ABI-L(?:1b|2)-[A-Za-z0-9]+)/\d{4}/\d{3}/\d{2}/"
    r"OR_(?P<product>ABI-L(?:1b|2)-[A-Za-z0-9]+)-(?P<mode>M\d)(?:C(?P<band>\d{2}))?_"
    r"(?P<satellite>G\d{2})_s(?P<s>\d{14})_e(?P<e>\d{14})_c(?P<c>\d{14})\.nc$"
)
BUCKETS = {"G16": "noaa-goes16", "G17": "noaa-goes17", "G18": "noaa-goes18", "G19": "noaa-goes19"}


def _require_utc(name: str, value: datetime) -> None:
    if value.tzinfo is None or value.utcoffset() != timedelta(0):
        raise ValueError(f"{name} must be a timezone-aware UTC datetime, not {value!r}")


@dataclass(frozen=True)
class ScanRef:
    """One scan file to virtualize: its https URL and the scan start and end in UTC."""

    url: str
    start: datetime
    end: datetime

    def __post_init__(self) -> None:
        _require_utc("start", self.start)
        _require_utc("end", self.end)


@dataclass(frozen=True)
class ScanKey:
    """The facts in one NOAA object key."""

    key: str
    product: str
    mode: str
    band: int | None
    satellite: str
    start: datetime
    end: datetime
    created: datetime

    def ref(self, bucket: str | None = None) -> ScanRef:
        """The scan reference, in the satellite's NOAA bucket unless ``bucket`` names another."""
        return ScanRef(
            url=object_url(bucket or BUCKETS[self.satellite], self.key),
            start=self.start,
            end=self.end,
        )


def stamp(text: str) -> datetime:
    """Parse YYYYDDDHHMMSSs: year, day of year, hour, minute, second, tenths. The clock is UTC."""
    base = datetime.strptime(text[:11], "%Y%j%H%M").replace(tzinfo=UTC)
    return base + timedelta(seconds=int(text[11:13]) + int(text[13]) / 10)


def parse_key(key: str) -> ScanKey:
    """The facts in a NOAA ABI object key. Raises ValueError for any other key."""
    m = KEY_RE.match(key)
    if not m or not m["product"].startswith(m["prefix"]):
        raise ValueError(f"not a GOES ABI key: {key}")
    return ScanKey(
        key=key,
        product=m["product"],
        mode=m["mode"],
        band=int(m["band"]) if m["band"] else None,
        satellite=m["satellite"],
        start=stamp(m["s"]),
        end=stamp(m["e"]),
        created=stamp(m["c"]),
    )


def object_url(bucket: str, key: str) -> str:
    """The public https URL of an object in a NOAA bucket."""
    return f"https://{bucket}.s3.amazonaws.com/{key}"
