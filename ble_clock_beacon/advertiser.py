"""BlueZ LEAdvertisingManager1 wrapper.

BlueZ accepts a custom advertisement object exported on the system DBus and
takes care of feeding it to the controller. We expose a single 128-bit Service
UUID with a 5-byte ServiceData payload; BlueZ encodes that as AD type 0x21
(Service Data - 128-bit UUID), which is what the clock firmware filters on.

BlueZ has no stable API to mutate a registered advertisement's payload, so
update_payload() cycles the registration on the BlueZ manager side. The
exported DBus object and its proxy to the manager are kept across cycles to
avoid re-introspecting BlueZ on every tick.
"""

# NOTE: do NOT add `from __future__ import annotations` to this module.
# The dbus-next `@method` / `@dbus_property` decorators read the literal
# return annotation strings (e.g. "s", "as", "a{sv}") at class-creation
# time as DBus signatures — not as Python type hints. PEP 563 turns those
# into deferred strings and the decorator raises ValueError on import.
import asyncio
import logging

from dbus_next import BusType, DBusError, Variant
from dbus_next.aio import MessageBus, ProxyInterface
from dbus_next.constants import PropertyAccess
from dbus_next.service import ServiceInterface, dbus_property, method

from .protocol import SERVICE_UUID

logger = logging.getLogger(__name__)

BLUEZ_BUS = "org.bluez"
ADAPTER_PATH = "/org/bluez/hci0"
ADV_MANAGER_IFACE = "org.bluez.LEAdvertisingManager1"
ADV_PATH = "/com/sasaki/bleclockbeacon/adv0"

ADV_INTERVAL_MS = 100


class TimeAdvertisement(ServiceInterface):
    def __init__(self, payload: bytes) -> None:
        super().__init__("org.bluez.LEAdvertisement1")
        self._payload = payload

    def set_payload(self, payload: bytes) -> None:
        self._payload = payload

    @dbus_property(access=PropertyAccess.READ)
    def Type(self) -> "s":  # noqa: F821, N802
        return "broadcast"

    @dbus_property(access=PropertyAccess.READ)
    def ServiceUUIDs(self) -> "as":  # noqa: F821, N802
        return [SERVICE_UUID]

    @dbus_property(access=PropertyAccess.READ)
    def ServiceData(self) -> "a{sv}":  # noqa: F821, N802
        return {SERVICE_UUID: Variant("ay", self._payload)}

    @dbus_property(access=PropertyAccess.READ)
    def MinInterval(self) -> "u":  # noqa: F821, N802
        return ADV_INTERVAL_MS

    @dbus_property(access=PropertyAccess.READ)
    def MaxInterval(self) -> "u":  # noqa: F821, N802
        return ADV_INTERVAL_MS

    @method()
    def Release(self) -> None:  # noqa: N802
        logger.info("advertisement released by BlueZ")


class Advertiser:
    def __init__(self) -> None:
        self._bus: MessageBus | None = None
        self._manager: ProxyInterface | None = None
        self._adv: TimeAdvertisement | None = None
        self._last_payload: bytes | None = None

    async def _ensure_connected(self) -> ProxyInterface:
        if self._manager is not None:
            return self._manager
        self._bus = await MessageBus(bus_type=BusType.SYSTEM).connect()
        introspect = await self._bus.introspect(BLUEZ_BUS, ADAPTER_PATH)
        proxy = self._bus.get_proxy_object(BLUEZ_BUS, ADAPTER_PATH, introspect)
        self._manager = proxy.get_interface(ADV_MANAGER_IFACE)
        self._adv = TimeAdvertisement(b"\x00" * 5)
        self._bus.export(ADV_PATH, self._adv)
        return self._manager

    async def update_payload(self, payload: bytes) -> None:
        if payload == self._last_payload:
            return
        manager = await self._ensure_connected()
        assert self._adv is not None
        if self._last_payload is not None:
            try:
                await manager.call_unregister_advertisement(ADV_PATH)
            except DBusError as exc:
                logger.warning("UnregisterAdvertisement failed: %s", exc)
        self._adv.set_payload(payload)
        await manager.call_register_advertisement(ADV_PATH, {})
        self._last_payload = payload
        logger.debug("registered advertisement, payload=%s", payload.hex())

    async def stop(self) -> None:
        if self._manager is not None and self._last_payload is not None:
            try:
                await self._manager.call_unregister_advertisement(ADV_PATH)
            except DBusError as exc:
                logger.warning("UnregisterAdvertisement failed: %s", exc)
        self._last_payload = None

    async def close(self) -> None:
        await self.stop()
        if self._bus is not None:
            try:
                self._bus.unexport(ADV_PATH)
            except Exception as exc:  # dbus_next raises bare Exception here
                logger.warning("unexport failed: %s", exc)
            self._bus.disconnect()
            self._bus = None
        self._manager = None
        self._adv = None
