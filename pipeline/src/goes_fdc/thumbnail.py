"""Render the collection thumbnail: fire radiative power on the CONUS grid.

    uv run --group viz python -m goes_fdc.thumbnail --time 2025-01-08T06:00 \\
        --out catalog/goes-18/abi-l2-fdcc/thumbnail.png

With --time, the script reads one scan, about 60 chunk requests per variable.
Without it, the script finds the scan with the highest total FRP, which reads
every chunk of every scan. Use that only on a small store.

Matplotlib is in the `viz` dependency group, so it stays out of the pipeline install.
"""
from __future__ import annotations

import argparse
from pathlib import Path

import numpy as np
import xarray as xr

from . import store

SATELLITE = "G18"


def main() -> None:
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--store", default=str(store.DEFAULT_STORE))
    p.add_argument("--time", help="UTC, ISO 8601. The nearest scan is drawn.")
    p.add_argument("--out", type=Path, required=True)
    args = p.parse_args()

    import matplotlib

    matplotlib.use("Agg")
    import matplotlib.pyplot as plt

    repo = store.open_repo(args.store, SATELLITE)
    ds = xr.open_zarr(repo.readonly_session("main").store, consolidated=False)
    if args.time:
        scan = ds.sel(time=np.datetime64(args.time), method="nearest")
    else:
        totals = ds.Power.where(ds.Power > 0).sum(("y", "x")).compute()
        scan = ds.isel(time=int(totals.argmax()))
    power = scan.Power.values

    # Center on the strongest fire pixel, with about 120 km of context each way.
    cy, cx = np.unravel_index(np.nanargmax(power), power.shape)
    pad = 60
    y0, y1 = max(cy - pad, 0), min(cy + pad + 1, power.shape[0])
    x0, x1 = max(cx - pad, 0), min(cx + pad + 1, power.shape[1])
    mask = scan.Mask.values[y0:y1, x0:x1]

    fig, ax = plt.subplots(figsize=(6.4, 3.84), dpi=100)
    ax.imshow(mask, cmap="Greys", aspect="equal", interpolation="nearest")
    fy, fx = np.where(power[y0:y1, x0:x1] > 0)
    ax.scatter(fx, fy, c=power[y0:y1, x0:x1][fy, fx], s=90, marker="s", cmap="inferno",
               vmin=0, vmax=200, edgecolors="white", linewidths=0.4)
    ax.set_axis_off()
    ax.set_title(f"GOES-18 FDCC, 2 km pixels: fire radiative power, {str(scan.time.values)[:16]}Z", fontsize=8)
    fig.tight_layout(pad=0.4)
    args.out.parent.mkdir(parents=True, exist_ok=True)
    fig.savefig(args.out)
    print(f"wrote {args.out}")


if __name__ == "__main__":
    main()
