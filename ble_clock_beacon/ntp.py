"""systemd-timesyncd readiness check.

We use `timedatectl show -p NTPSynchronized --value` because it has zero
runtime dependencies and is unambiguous (returns the literal "yes"/"no"). The
DBus alternative on org.freedesktop.timedate1 is equivalent but heavier.
"""

from __future__ import annotations

import logging
import subprocess
import time

logger = logging.getLogger(__name__)


def is_ntp_synchronized() -> bool:
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


def wait_for_ntp_sync(timeout: float = 300.0, poll_interval: float = 2.0) -> bool:
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if is_ntp_synchronized():
            return True
        time.sleep(poll_interval)
    return False
