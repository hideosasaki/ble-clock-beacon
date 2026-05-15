"""Main loop: wait for NTP, then advertise during each transmit window."""

from __future__ import annotations

import asyncio
import logging
import signal

from .advertiser import Advertiser
from .ntp import wait_for_ntp_sync
from .protocol import build_payload
from .scheduler import (
    seconds_until_next_window,
    utc_now,
    window_for,
)

logger = logging.getLogger(__name__)

NTP_WAIT_TIMEOUT_S = 300.0
NTP_STABILIZE_DELAY_S = 30.0
# Re-register at 1 Hz; the clock RTC is second-precision so finer updates
# would only add DBus churn without improving sync accuracy.
UPDATE_INTERVAL_S = 1.0
IDLE_MAX_SLEEP_S = 1.0


async def _sleep_or_stop(stop: asyncio.Event, seconds: float) -> None:
    if seconds <= 0:
        return
    try:
        await asyncio.wait_for(stop.wait(), timeout=seconds)
    except asyncio.TimeoutError:
        pass


async def run() -> int:
    stop = asyncio.Event()
    loop = asyncio.get_running_loop()
    for sig in (signal.SIGINT, signal.SIGTERM):
        loop.add_signal_handler(sig, stop.set)

    logger.info("waiting for NTP sync (timeout=%.0fs)", NTP_WAIT_TIMEOUT_S)
    synced = await asyncio.to_thread(wait_for_ntp_sync, NTP_WAIT_TIMEOUT_S)
    if not synced:
        logger.error("NTP did not synchronize; aborting")
        return 1
    logger.info("NTP synced; sleeping %.0fs for stabilization", NTP_STABILIZE_DELAY_S)
    await _sleep_or_stop(stop, NTP_STABILIZE_DELAY_S)

    advertiser = Advertiser()
    try:
        while not stop.is_set():
            now = utc_now()
            window = window_for(now)
            if window is not None:
                _, end = window
                await advertiser.update_payload(build_payload(int(now.timestamp())))
                # Align to the next integer second so the loop ticks once per
                # second regardless of how long update_payload took.
                to_next_second = 1.0 - (now.timestamp() % 1.0)
                remaining = (end - now).total_seconds()
                await _sleep_or_stop(stop, min(to_next_second, remaining))
            else:
                await advertiser.stop()
                await _sleep_or_stop(
                    stop, min(IDLE_MAX_SLEEP_S, seconds_until_next_window(now))
                )
    finally:
        await advertiser.close()
    return 0


def main() -> int:
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)s %(name)s: %(message)s",
    )
    return asyncio.run(run())
