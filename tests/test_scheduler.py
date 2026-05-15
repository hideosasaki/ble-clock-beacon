from __future__ import annotations

from datetime import datetime, timedelta, timezone

import pytest

from ble_clock_beacon.scheduler import (
    in_window,
    next_window_start,
    seconds_until_next_window,
    window_for,
)

UTC = timezone.utc


def t(h: int, m: int, s: int, day: int = 15) -> datetime:
    return datetime(2026, 5, day, h, m, s, tzinfo=UTC)


@pytest.mark.parametrize(
    "moment",
    [
        t(11, 59, 30),  # start of the :00 window
        t(11, 59, 59),
        t(12, 0, 0),
        t(12, 0, 29),  # last second still inside
        t(12, 14, 30),
        t(12, 15, 29),
        t(12, 29, 45),
        t(12, 44, 31),
    ],
)
def test_in_window_true(moment):
    assert in_window(moment)


@pytest.mark.parametrize(
    "moment",
    [
        t(11, 59, 29),  # one second before the window opens
        t(12, 0, 30),   # window closed (exclusive end)
        t(12, 1, 0),
        t(12, 10, 0),
        t(12, 15, 30),
        t(12, 20, 0),
        t(12, 30, 30),
        t(12, 45, 30),
    ],
)
def test_in_window_false(moment):
    assert not in_window(moment)


def test_window_for_returns_bounds():
    win = window_for(t(12, 14, 45))
    assert win == (t(12, 14, 30), t(12, 15, 30))


def test_next_window_start_within_hour():
    # At 12:05, the next window starts at 12:14:30.
    assert next_window_start(t(12, 5, 0)) == t(12, 14, 30)


def test_next_window_start_crosses_hour():
    # At 12:50, the next window starts at 12:59:30.
    assert next_window_start(t(12, 50, 0)) == t(12, 59, 30)


def test_next_window_start_crosses_day_boundary():
    # 23:50 -> 23:59:30 same day.
    assert next_window_start(t(23, 50, 0, day=15)) == t(23, 59, 30, day=15)


def test_seconds_until_next_window_during_idle():
    # At 12:05:00 the next window opens at 12:14:30 -> 570s.
    assert seconds_until_next_window(t(12, 5, 0)) == pytest.approx(570.0)


def test_seconds_until_next_window_inside_window_is_positive():
    # Inside a window, next_window_start still returns the next window after
    # the current one, never the current one itself.
    val = seconds_until_next_window(t(12, 0, 0))
    assert val > 0
    # The window from 11:59:30 to 12:00:30 is current; next is 12:14:30.
    assert val == pytest.approx(timedelta(minutes=14, seconds=30).total_seconds())
