"""Render the collection thumbnail: fire radiative power on the CONUS grid.

    uv run --group viz python -m goes_fdc.thumbnail --store local/smoke/icechunk \\
        --out catalog/goes-18/abi-l2-fdcc/thumbnail.png

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
    p.add_argument("--store", type=Path, required=True)
    p.add_argument("--out", type=Path, required=True)
    args = p.parse_args()

    import matplotlib

    matplotlib.use("Agg")
    import matplotlib.pyplot as plt

    repo = store.open_repo(args.store, SATELLITE)
    ds = xr.open_zarr(repo.readonly_session("main").store, consolidated=False)
    totals = ds.Power.where(ds.Power > 0).sum(("y", "x")).compute()
    scan = ds.isel(time=int(totals.argmax()))
    power = scan.Power.values

    yy, xx = np.where(power > 0)
    pad = 20  # pixels of context around the fire pixels, about 40 km
    y0, y1 = max(yy.min() - pad, 0), min(yy.max() + pad + 1, power.shape[0])
    x0, x1 = max(xx.min() - pad, 0), min(xx.max() + pad + 1, power.shape[1])
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
