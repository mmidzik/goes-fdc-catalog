"""goes-fdc: build or extend the local virtual Zarr store."""
from __future__ import annotations

import argparse
from datetime import datetime, timezone
from pathlib import Path

from . import keys, store, virtualize

BATCH = 288  # about one day of CONUS scans per Icechunk commit


def _utc(s: str) -> datetime:
    return datetime.fromisoformat(s).replace(tzinfo=timezone.utc)


def build(args: argparse.Namespace) -> None:
    start, end = _utc(args.start), _utc(args.end)
    scans = keys.list_scans(args.satellite, args.product, start, end)
    repo = store.open_repo(args.out / "icechunk", args.satellite)
    seen = store.last_time(repo)
    if seen is not None:
        cutoff = datetime.fromtimestamp(seen.astype("datetime64[s]").astype(int), timezone.utc)
        scans = [s for s in scans if s.start > cutoff]
    print(f"{len(scans)} new scans in [{start:%F %T}, {end:%F %T})")
    for i in range(0, len(scans), BATCH):
        chunk = scans[i : i + BATCH]
        cube = virtualize.build_cube(chunk, workers=args.workers)
        snap = store.append(repo, cube, f"{chunk[0].start:%FT%TZ} to {chunk[-1].start:%FT%TZ}")
        store.export_kerchunk(cube, args.out / "refs" / f"{chunk[0].start:%Y%m%dT%H%M}.parquet")
        print(f"committed {snap}: {len(chunk)} scans, last {chunk[-1].start:%F %T}")


def main() -> None:
    p = argparse.ArgumentParser(prog="goes-fdc", description=__doc__)
    sub = p.add_subparsers(required=True)
    b = sub.add_parser("build", help="virtualize a time window and append it to the store")
    b.add_argument("--satellite", default="G18", choices=sorted(keys.BUCKETS))
    b.add_argument("--product", default="ABI-L2-FDCC")
    b.add_argument("--start", required=True, help="UTC, ISO 8601, e.g. 2025-01-07T00:00")
    b.add_argument("--end", required=True, help="UTC, exclusive")
    b.add_argument("--out", type=Path, default=Path("local"))
    b.add_argument("--workers", type=int, default=16)
    b.set_defaults(func=build)
    args = p.parse_args()
    args.func(args)
