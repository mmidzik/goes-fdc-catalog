"""goes-fdc: build or extend the local virtual Zarr store."""
from __future__ import annotations

import argparse
import logging
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

from . import keys, store, virtualize

# One Icechunk commit per UTC day, about 288 CONUS scans. A day is listed,
# virtualized, and committed before the next day starts, so a long build holds
# one day in memory and a stopped build resumes at the next day.
DAY = timedelta(days=1)

log = logging.getLogger(__name__)

ROOT = Path(__file__).resolve().parents[3]
COLLECTION = "goes-18-fdcc"


def default_public_base() -> str | None:
    """`public_base` from catalog.publish.yaml, or None outside the repository."""
    if not (ROOT / "catalog.publish.yaml").exists():
        return None
    sys.path.insert(0, str(ROOT / "tools"))
    from publish import load_config

    return load_config(ROOT / "catalog.publish.yaml")["public_base"]


def collection_url(public_base: str | None) -> str | None:
    """The published collection.json, for the store's `stac:link` attribute."""
    return f"{public_base.rstrip('/')}/{COLLECTION}/collection.json" if public_base else None


def _utc(s: str) -> datetime:
    return datetime.fromisoformat(s).replace(tzinfo=timezone.utc)


def build(args: argparse.Namespace) -> None:
    start, end = _utc(args.start), _utc(args.end)
    link = collection_url(args.public_base)
    repo = store.open_repo(args.store, args.satellite)
    seen = store.last_time(repo)
    cutoff = None
    if seen is not None:
        cutoff = datetime.fromtimestamp(seen.astype("datetime64[s]").astype(int), timezone.utc)
        log.info("store ends at %s; resuming after it", f"{cutoff:%F %T}")
    day = start.replace(hour=0, minute=0, second=0, microsecond=0)
    total = 0
    while day < end:
        lo, hi = max(day, start), min(day + DAY, end)
        day += DAY
        if cutoff is not None and hi <= cutoff:
            continue
        scans = keys.list_scans(args.satellite, args.product, lo, hi)
        if cutoff is not None:
            scans = [s for s in scans if s.start > cutoff]
        if not scans:
            log.info("%s: no new scans", f"{lo:%F}")
            continue
        log.info("%s: listed %d scans", f"{lo:%F}", len(scans))
        cube = virtualize.build_cube(scans, workers=args.workers, collection_url=link)
        if cube is None:
            log.info("%s: no usable scans", f"{lo:%F}")
            continue
        log.info("%s: virtualized", f"{lo:%F}")
        snap = store.append(repo, cube, f"{scans[0].start:%FT%TZ} to {scans[-1].start:%FT%TZ}")
        log.info("%s: committed %s", f"{lo:%F}", snap)
        total += len(scans)
    log.info("done: %d scans added", total)


def main() -> None:
    p = argparse.ArgumentParser(prog="goes-fdc", description=__doc__)
    sub = p.add_subparsers(required=True)
    b = sub.add_parser("build", help="virtualize a time window and append it to the store")
    b.add_argument("--satellite", default="G18", choices=sorted(keys.BUCKETS))
    b.add_argument("--product", default="ABI-L2-FDCC")
    b.add_argument("--start", required=True, help="UTC, ISO 8601, e.g. 2025-01-07T00:00")
    b.add_argument("--end", required=True, help="UTC, exclusive")
    b.add_argument("--store", default=str(store.DEFAULT_STORE), help="local path or s3://bucket/prefix of the Icechunk repo")
    b.add_argument("--workers", type=int, default=16)
    b.add_argument("--public-base", default=default_public_base(),
                   help="public base URL of the catalog, for the store's link to its collection "
                        "(default: public_base in catalog.publish.yaml)")
    b.set_defaults(func=build)
    args = p.parse_args()
    # Each line carries its time, so the gap between two lines is the time a step took.
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
    args.func(args)
