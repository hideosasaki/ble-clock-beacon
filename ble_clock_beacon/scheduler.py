"""Transmit window scheduling.

The clock wakes every 15 minutes at HH:00/15/30/45 with a 500 ms scan window.
To cover that with margin we transmit for 60 s starting 30 s before each wake,
so the windows (UTC, system clock) are:

    HH:59:30 .. HH+1:00:30
    HH:14:30 .. HH:15:30
    HH:29:30 .. HH:30:30
    HH:44:30 .. HH:45:30

About 4 minutes of advertising per hour; the remaining ~56 min the radio is
idle so the rest of the household BLE traffic is undisturbed.
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

WINDOW_DURATION = timedelta(seconds=60)
WINDOW_LEAD = timedelta(seconds=30)
WINDOW_CENTERS_MIN = (0, 15, 30, 45)


def _surrounding_centers(now: datetime) -> list[datetime]:
    base = now.replace(minute=0, second=0, microsecond=0)
    return [
        base + timedelta(hours=h, minutes=m)
        for h in (-1, 0, 1)
        for m in WINDOW_CENTERS_MIN
    ]


def window_for(now: datetime) -> tuple[datetime, datetime] | None:
    for center in _surrounding_centers(now):
        start = center - WINDOW_LEAD
        end = start + WINDOW_DURATION
        if start <= now < end:
            return start, end
    return None


def in_window(now: datetime) -> bool:
    return window_for(now) is not None


def next_window_start(now: datetime) -> datetime:
    for center in _surrounding_centers(now):
        start = center - WINDOW_LEAD
        if start > now:
            return start
    raise AssertionError("surrounding centers always include a future start")


def seconds_until_next_window(now: datetime) -> float:
    delta = next_window_start(now) - now
    return max(0.0, delta.total_seconds())


def utc_now() -> datetime:
    return datetime.now(timezone.utc)
