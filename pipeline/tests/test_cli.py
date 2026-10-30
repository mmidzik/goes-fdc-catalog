import threading
import time
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timezone

import pytest

from goes_fdc import cli


def utc(*args):
    return datetime(*args, tzinfo=timezone.utc)


def test_day_windows_clip_to_start_and_end():
    windows = list(cli.day_windows(utc(2025, 1, 7, 6), utc(2025, 1, 9, 12), None))
    assert windows == [
        (utc(2025, 1, 7, 6), utc(2025, 1, 8)),
        (utc(2025, 1, 8), utc(2025, 1, 9)),
        (utc(2025, 1, 9), utc(2025, 1, 9, 12)),
    ]


def test_day_windows_skip_days_before_the_cutoff():
    windows = list(cli.day_windows(utc(2025, 1, 7), utc(2025, 1, 10), utc(2025, 1, 8, 3)))
    assert [lo for lo, _ in windows] == [utc(2025, 1, 8), utc(2025, 1, 9)]


def test_in_order_yields_in_window_order_when_days_finish_out_of_order():
    windows = [(utc(2025, 1, d), utc(2025, 1, d + 1)) for d in range(1, 9)]
    # Earlier days take longer, so later days finish first.
    delays = {lo: 0.01 * (9 - lo.day) for lo, _ in windows}

    def task(lo, hi):
        time.sleep(delays[lo])
        return lo.day

    with ThreadPoolExecutor(max_workers=4) as pool:
        out = list(cli.in_order(pool, iter(windows), task, depth=4))
    assert out == [(lo, lo.day) for lo, _ in windows]


def test_in_order_keeps_at_most_depth_days_in_flight():
    windows = [(utc(2025, 1, d), utc(2025, 1, d + 1)) for d in range(1, 11)]
    lock = threading.Lock()
    running = peak = 0

    def task(lo, hi):
        nonlocal running, peak
        with lock:
            running += 1
            peak = max(peak, running)
        time.sleep(0.01)
        with lock:
            running -= 1

    with ThreadPoolExecutor(max_workers=8) as pool:
        list(cli.in_order(pool, iter(windows), task, depth=3))
    assert peak <= 3


def test_in_order_stops_at_a_failed_day_and_cancels_the_rest():
    # A failed day must stop the build, and no later day may reach the caller.
    windows = [(utc(2025, 1, d), utc(2025, 1, d + 1)) for d in range(1, 11)]
    started = []

    def task(lo, hi):
        started.append(lo.day)
        if lo.day == 2:
            raise ValueError("bad day")
        time.sleep(0.05)
        return lo.day

    seen = []
    with ThreadPoolExecutor(max_workers=1) as pool:
        with pytest.raises(ValueError, match="bad day"):
            for lo, day in cli.in_order(pool, iter(windows), task, depth=3):
                seen.append(day)
    assert seen == [1]
    assert max(started) < 10
