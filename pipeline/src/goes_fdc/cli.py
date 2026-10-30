"""goes-fdc: build or extend the local virtual Zarr store."""
from __future__ import annotations

import argparse
import importlib.util
import logging
import multiprocessing
import sys
from collections import deque
from collections.abc import Callable, Iterator
from concurrent.futures import Executor, ProcessPoolExecutor
from datetime import datetime, timedelta, timezone
from functools import partial
from pathlib import Path

from . import collection, keys, store, virtualize

# One Icechunk commit per UTC day, about 288 CONUS scans. Worker processes list
# and virtualize days ahead of the commit. One process commits the days in time
# order, so a stopped build resumes at the next day. A build holds at most
# --processes days in memory, plus the day it commits.
DAY = timedelta(days=1)

# Each line carries its time, so the gap between two lines is the time a step took.
LOG_FORMAT = "%(asctime)s %(levelname)s %(processName)s %(message)s"

log = logging.getLogger(__name__)

ROOT = Path(__file__).resolve().parents[3]


def default_public_base() -> str | None:
    """`public_base` from catalog.publish.yaml, or None outside the repository."""
    config = ROOT / "catalog.publish.yaml"
    if not config.exists():
        return None
    # Load tools/publish.py by path, so its directory does not join sys.path.
    # Its dataclasses need the module in sys.modules while it runs.
    spec = importlib.util.spec_from_file_location("_goes_fdc_publish", ROOT / "tools" / "publish.py")
    publish = sys.modules.setdefault(spec.name, importlib.util.module_from_spec(spec))
    spec.loader.exec_module(publish)
    return publish.load_config(config)["public_base"]


def _utc(s: str) -> datetime:
    return datetime.fromisoformat(s).replace(tzinfo=timezone.utc)


def setup_logging() -> None:
    logging.basicConfig(level=logging.INFO, format=LOG_FORMAT)


def day_windows(start: datetime, end: datetime, cutoff: datetime | None) -> Iterator[tuple[datetime, datetime]]:
    """The [lo, hi) part of each UTC day in [start, end) that can hold scans after cutoff."""
    day = start.replace(hour=0, minute=0, second=0, microsecond=0)
    while day < end:
        lo, hi = max(day, start), min(day + DAY, end)
        day += DAY
        if cutoff is None or hi > cutoff:
            yield lo, hi


def virtualize_day(lo: datetime, hi: datetime, *, satellite: str, product: str,
                   cutoff: datetime | None, workers: int):
    """List and virtualize one day. Runs in a worker process.

    Returns the new scans and their cube. The cube is None when no scan is new
    or usable.
    """
    scans = keys.list_scans(satellite, product, lo, hi)
    if cutoff is not None:
        scans = [s for s in scans if s.start > cutoff]
    if not scans:
        return scans, None
    log.info("%s: listed %d scans", f"{lo:%F}", len(scans))
    cube = virtualize.build_cube(scans, workers=workers)
    log.info("%s: virtualized", f"{lo:%F}")
    return scans, cube


def in_order(pool: Executor, windows: Iterator[tuple[datetime, datetime]],
             task: Callable, depth: int) -> Iterator:
    """Run task(lo, hi) on the pool for each window, and yield (lo, result) in window order.

    At most depth windows are in flight. The next window starts as soon as the
    caller takes a result, so the pool works while the caller commits.
    """
    pending = deque()

    def submit_next() -> None:
        window = next(windows, None)
        if window is not None:
            pending.append((window[0], pool.submit(task, *window)))

    try:
        for _ in range(depth):
            submit_next()
        while pending:
            lo, future = pending.popleft()
            result = future.result()
            submit_next()
            yield lo, result
    finally:
        # A failed day stops the build. Days after it must not commit, so
        # cancel the ones that have not started.
        for _, future in pending:
            future.cancel()


def build(args: argparse.Namespace) -> None:
    start, end = _utc(args.start), _utc(args.end)
    public_base = args.public_base or default_public_base()
    link = collection.collection_url(public_base) if public_base else None
    repo = store.open_repo(args.store, args.satellite)
    seen = store.last_time(repo)
    cutoff = None
    if seen is not None:
        cutoff = datetime.fromtimestamp(seen.astype("datetime64[s]").astype(int), timezone.utc)
        log.info("store ends at %s; resuming after it", f"{cutoff:%F %T}")
    task = partial(virtualize_day, satellite=args.satellite, product=args.product,
                   cutoff=cutoff, workers=args.workers)
    total = 0
    # Spawn, not fork. This process already runs the Icechunk and obstore
    # thread pools, and a forked child of a threaded process can deadlock.
    context = multiprocessing.get_context("spawn")
    with ProcessPoolExecutor(max_workers=args.processes, mp_context=context,
                             initializer=setup_logging) as pool:
        windows = day_windows(start, end, cutoff)
        for lo, (scans, cube) in in_order(pool, windows, task, args.processes):
            if not scans:
                log.info("%s: no new scans", f"{lo:%F}")
                continue
            if cube is None:
                log.info("%s: no usable scans", f"{lo:%F}")
                continue
            snap = store.append(repo, cube, f"{scans[0].start:%FT%TZ} to {scans[-1].start:%FT%TZ}", link)
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
    b.add_argument("--workers", type=int, default=16,
                   help="threads per process that read scan headers")
    b.add_argument("--processes", type=int, default=2,
                   help="days virtualized at once, one process each")
    b.add_argument("--public-base", default=None,
                   help="public base URL of the catalog, for the store's link to its collection "
                        "(default: public_base in catalog.publish.yaml)")
    b.set_defaults(func=build)
    args = p.parse_args()
    setup_logging()
    args.func(args)
