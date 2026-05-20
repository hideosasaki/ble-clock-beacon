"""BlueZ LEAdvertisingManager1 wrapper.

BlueZ accepts a custom advertisement object exported on the system DBus and
takes care of feeding it to the controller. We expose a single 128-bit Service
UUID with a 5-byte ServiceData payload; BlueZ encodes that as AD type 0x21
(Service Data - 128-bit UUID), which is what the clock firmware filters on.

We register the advertisement once when a transmit window opens, refresh the
ServiceData payload by emitting `PropertiesChanged` while the window is open,
and unregister once when the window closes. Cycling the registration on every
payload update was found to break Realtek-based controllers with kernel
`Unexpected advertising set terminated event` warnings and an ActiveInstances
count stuck at zero.

BlueZ writes the `Active` property on the advertisement object after the
controller starts the advertising instance and again before tear-down, so we
expose it as a writable boolean rather than letting dbus-next reject the
write with `the property is readonly`.
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
        self._active = False

    def set_payload(self, payload: bytes) -> None:
        self._payload = payload

    def _service_data_dict(self) -> dict:
        return {SERVICE_UUID: Variant("ay", self._payload)}

    @dbus_property(access=PropertyAccess.READ)
    def Type(self) -> "s":  # noqa: F821, N802
        return "broadcast"

    @dbus_property(access=PropertyAccess.READ)
    def ServiceUUIDs(self) -> "as":  # noqa: F821, N802
        return [SERVICE_UUID]

    @dbus_property(access=PropertyAccess.READ)
    def ServiceData(self) -> "a{sv}":  # noqa: F821, N802
        return self._service_data_dict()

    @dbus_property(access=PropertyAccess.READ)
    def MinInterval(self) -> "u":  # noqa: F821, N802
        return ADV_INTERVAL_MS

    @dbus_property(access=PropertyAccess.READ)
    def MaxInterval(self) -> "u":  # noqa: F821, N802
        return ADV_INTERVAL_MS

    # BlueZ reads TxPower on every advertise; returning 0 lets the
    # controller pick. Omitting it logs a property-not-found error
    # per transmit window.
    @dbus_property(access=PropertyAccess.READ)
    def TxPower(self) -> "n":  # noqa: F821, N802
        return 0

    @dbus_property(access=PropertyAccess.READWRITE)
    def Active(self) -> "b":  # noqa: F821, N802
        return self._active

    @Active.setter  # type: ignore[no-redef]
    def Active(self, value: "b") -> None:  # noqa: F821, N802
        self._active = bool(value)
        logger.debug("BlueZ set Active=%s", self._active)

    @method()
    def Release(self) -> None:  # noqa: N802
        logger.info("advertisement released by BlueZ")


class Advertiser:
    def __init__(self) -> None:
        self._bus: MessageBus | None = None
        self._manager: ProxyInterface | None = None
        self._adv: TimeAdvertisement | None = None
        # None = not currently registered with BlueZ.
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
        manager = await self._ensure_connected()
        assert self._adv is not None

        if self._last_payload is None:
            self._adv.set_payload(payload)
            await manager.call_register_advertisement(ADV_PATH, {})
            self._last_payload = payload
            logger.info("registered advertisement, payload=%s", payload.hex())
            return

        if payload == self._last_payload:
            return

        self._adv.set_payload(payload)
        try:
            self._adv.emit_properties_changed(
                {"ServiceData": self._adv._service_data_dict()}
            )
        except Exception as exc:
            logger.warning("emit_properties_changed failed: %s", exc)
        self._last_payload = payload
        logger.debug("updated payload via PropertiesChanged, payload=%s", payload.hex())

    async def stop(self) -> None:
        if self._last_payload is not None and self._manager is not None:
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
