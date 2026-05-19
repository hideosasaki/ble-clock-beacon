"""NTP synchronization probe.

On systemd hosts we shell out to ``timedatectl show -p NTPSynchronized
--value`` (zero runtime dependencies, unambiguous ``yes``/``no``).

On non-systemd hosts (busybox / OpenWrt, Alpine, container images
without ``timedatectl``) we fall back to ``adjtimex(2)`` via ``ctypes``.
That syscall is the same source ``timedatectl`` itself reads, so it
works regardless of the NTP client in use (``chrony``, ``ntpd``,
``busybox sntp``, ...).

Both signals are required from ``adjtimex``: the return code must not
be ``TIME_ERROR`` *and* ``STA_UNSYNC`` must be cleared. Either check
alone is too lenient — e.g. chrony clears ``STA_UNSYNC`` before fully
converging.
"""

from __future__ import annotations

import ctypes
import logging
import shutil
import subprocess
import time

logger = logging.getLogger(__name__)

STA_UNSYNC = 0x0040
TIME_ERROR = 5


class _Timex(ctypes.Structure):
    _fields_ = [
        ("modes", ctypes.c_uint),
        ("offset", ctypes.c_long),
        ("freq", ctypes.c_long),
        ("maxerror", ctypes.c_long),
        ("esterror", ctypes.c_long),
        ("status", ctypes.c_int),
        ("constant", ctypes.c_long),
        ("precision", ctypes.c_long),
        ("tolerance", ctypes.c_long),
        ("time_sec", ctypes.c_long),
        ("time_usec", ctypes.c_long),
        ("tick", ctypes.c_long),
        ("ppsfreq", ctypes.c_long),
        ("jitter", ctypes.c_long),
        ("shift", ctypes.c_int),
        ("stabil", ctypes.c_long),
        ("jitcnt", ctypes.c_long),
        ("calcnt", ctypes.c_long),
        ("errcnt", ctypes.c_long),
        ("stbcnt", ctypes.c_long),
        ("tai", ctypes.c_int),
        ("_pad", ctypes.c_int * 11),
    ]


# Cached at import: PATH lookup and libc handle are immutable for the
# process lifetime, and is_ntp_synchronized() runs in a 2 s poll loop
# during startup.
_TIMEDATECTL = shutil.which("timedatectl")


def _resolve_adjtimex():
    # CDLL(None) opens the already-linked libc, so this works on both
    # glibc (libc.so.6) and musl (libc.musl-*.so.1) without hardcoding.
    try:
        libc = ctypes.CDLL(None, use_errno=True)
        fn = libc.adjtimex
    except (OSError, AttributeError) as exc:
        logger.warning("adjtimex unavailable: %s", exc)
        return None
    fn.argtypes = [ctypes.POINTER(_Timex)]
    fn.restype = ctypes.c_int
    return fn


_ADJTIMEX = _resolve_adjtimex()


def _check_timedatectl() -> bool:
    try:
        result = subprocess.run(
            ["timedatectl", "show", "-p", "NTPSynchronized", "--value"],
            capture_output=True,
            text=True,
            timeout=5,
            check=True,
        )
    except (FileNotFoundError, subprocess.CalledProcessError, subprocess.TimeoutExpired) as exc:
        logger.warning("timedatectl query failed: %s", exc)
        return False
    return result.stdout.strip() == "yes"


def _check_adjtimex() -> bool:
    if _ADJTIMEX is None:
        return False
    tx = _Timex()
    rc = _ADJTIMEX(ctypes.byref(tx))
    if rc < 0 or rc == TIME_ERROR:
        return False
    return (tx.status & STA_UNSYNC) == 0


def is_ntp_synchronized() -> bool:
    if _TIMEDATECTL is not None:
        return _check_timedatectl()
    return _check_adjtimex()


def wait_for_ntp_sync(timeout: float = 300.0, poll_interval: float = 2.0) -> bool:
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if is_ntp_synchronized():
            return True
        time.sleep(poll_interval)
    return False
