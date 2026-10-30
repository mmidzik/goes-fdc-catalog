"""The nominal time between scans of one ABI scene."""

from __future__ import annotations

from collections.abc import Sequence

from .virtualize import ScanMode

# Nominal time between scans of one scene, as ISO 8601 durations, by the file's `timeline_id` (ABI scan
# mode) and `scene_id`. From the ABI scan modes in the GOES-R Product Definition and Users' Guide.
# Mode 4 scans only the full disk.
SCAN_CADENCE: dict[ScanMode, str] = {
    ("ABI Mode 3", "Full Disk"): "PT15M",
    ("ABI Mode 3", "CONUS"): "PT5M",
    ("ABI Mode 3", "Mesoscale"): "PT1M",
    ("ABI Mode 4", "Full Disk"): "PT5M",
    ("ABI Mode 6", "Full Disk"): "PT10M",
    ("ABI Mode 6", "CONUS"): "PT5M",
    ("ABI Mode 6", "Mesoscale"): "PT1M",
}


def time_step(scan_modes: Sequence[ScanMode]) -> str:
    """The nominal step between scans, from each scan's mode and scene.

    Every scan must share one mode and scene: a window across a mode change has no single step.
    """
    modes = set(scan_modes)
    if len(modes) != 1:
        raise ValueError(
            f"the scans span several ABI scan modes or scenes: {sorted(map(str, modes))}"
        )
    (mode,) = modes
    if mode not in SCAN_CADENCE:
        raise ValueError(f"no known cadence for ABI timeline_id {mode[0]!r}, scene_id {mode[1]!r}")
    return SCAN_CADENCE[mode]
