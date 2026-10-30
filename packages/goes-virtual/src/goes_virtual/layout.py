"""Which variables of an ABI file a cube keeps, read from the file's own metadata."""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass, replace

import xarray as xr

PIXEL_DIMS = ("y", "x")
# The ACDD attribute that marks NOAA's scene-extent variable.
EXTENT_ATTR = "geospatial_westbound_longitude"


@dataclass(frozen=True)
class Layout:
    """The variables of one file, by role.

    - pixel: the variables on the `y` × `x` grid
    - scalars: per-scan summary values. CF marks each with `cell_methods`,
      which states the statistic NOAA computed over the scan
    - projection: the variable that the pixel variables name in `grid_mapping`
    - extent: NOAA's scene-extent variable, with the ACDD bounding attributes
    """

    pixel: tuple[str, ...]
    scalars: tuple[str, ...]
    projection: str
    extent: str | None

    @property
    def kept(self) -> tuple[str, ...]:
        """The variables along `time` in the cube."""
        return (*self.pixel, *self.scalars)

    @property
    def loadable(self) -> list[str]:
        """The variables read as values. Everything else stays virtual."""
        return [
            "t",
            "x",
            "y",
            self.projection,
            *self.scalars,
            *([self.extent] if self.extent else []),
        ]

    def select(self, keep: Sequence[str] | None) -> Layout:
        """The layout with only the pixel and per-scan variables in ``keep``.

        ``None`` keeps every variable. The projection and the extent always stay.
        """
        if keep is None:
            return self
        unknown = [name for name in keep if name not in self.kept]
        if unknown:
            raise ValueError(f"{unknown} are not in the file; its variables are {list(self.kept)}")
        pixel = tuple(name for name in self.pixel if name in keep)
        if not pixel:
            raise ValueError(f"keep {list(keep)} names no pixel variable of {list(self.pixel)}")
        return replace(
            self, pixel=pixel, scalars=tuple(name for name in self.scalars if name in keep)
        )


def layout(ds: xr.Dataset) -> Layout:
    """The layout of one file, from its dimensions and CF and ACDD attributes."""
    pixel = tuple(sorted(str(n) for n, v in ds.data_vars.items() if v.dims == PIXEL_DIMS))
    if not pixel:
        raise ValueError("the file has no variable on the y and x grid")
    mappings = {ds[n].attrs.get("grid_mapping") for n in pixel}
    if len(mappings) != 1 or None in mappings:
        raise ValueError(
            f"the pixel variables do not share one grid_mapping: {sorted(map(str, mappings))}"
        )
    scalars = tuple(
        sorted(str(n) for n, v in ds.variables.items() if v.ndim == 0 and "cell_methods" in v.attrs)
    )
    extents = [str(n) for n, v in ds.variables.items() if v.ndim == 0 and EXTENT_ATTR in v.attrs]
    return Layout(
        pixel=pixel,
        scalars=scalars,
        projection=str(mappings.pop()),
        extent=extents[0] if extents else None,
    )
