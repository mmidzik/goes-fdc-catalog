"""goes-fdc: build or extend the local virtual Zarr store."""
from __future__ import annotations

import argparse
import time
from datetime import datetime, timedelta, timezone

from . import keys, store, virtualize

# One Icechunk commit per UTC day, about 288 CONUS scans. A day is listed,
# virtualized, and committed before the next day starts, so a long build holds
# one day in memory and a stopped build resumes at the next day.
DAY = timedelta(days=1)


def _utc(s: str) -> datetime:
    return datetime.fromisoformat(s).replace(tzinfo=timezone.utc)


def build(args: argparse.Namespace) -> None:
    start, end = _utc(args.start), _utc(args.end)
    repo = store.open_repo(args.store, args.satellite)
    seen = store.last_time(repo)
    cutoff = None
    if seen is not None:
        cutoff = datetime.fromtimestamp(seen.astype("datetime64[s]").astype(int), timezone.utc)
        print(f"store ends at {cutoff:%F %T}; resuming after it")
    day = start.replace(hour=0, minute=0, second=0, microsecond=0)
    total = 0
    while day < end:
        lo, hi = max(day, start), min(day + DAY, end)
        day += DAY
        if cutoff is not None and hi <= cutoff:
            continue
        t0 = time.monotonic()
        scans = keys.list_scans(args.satellite, args.product, lo, hi)
        if cutoff is not None:
            scans = [s for s in scans if s.start > cutoff]
        if not scans:
            print(f"{lo:%F}: no new scans")
            continue
        t1 = time.monotonic()
        cube = virtualize.build_cube(scans, workers=args.workers)
        t2 = time.monotonic()
        snap = store.append(repo, cube, f"{scans[0].start:%FT%TZ} to {scans[-1].start:%FT%TZ}")
        t3 = time.monotonic()
        total += len(scans)
        print(
            f"{lo:%F}: {len(scans)} scans, commit {snap}, "
            f"list {t1 - t0:.1f}s, virtualize {t2 - t1:.1f}s, commit {t3 - t2:.1f}s",
            flush=True,
        )
    print(f"done: {total} scans added")


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
    b.set_defaults(func=build)
    args = p.parse_args()
    args.func(args)
