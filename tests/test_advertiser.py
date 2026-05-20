"""Unit tests for advertiser.py that do not require a live BlueZ."""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock

from ble_clock_beacon.advertiser import Advertiser, TimeAdvertisement
from ble_clock_beacon.protocol import SERVICE_UUID, build_payload


def test_active_property_is_writable():
    # BlueZ writes Active after RegisterAdvertisement; without a writable
    # backing field dbus-next rejects the Set as "the property is readonly".
    adv = TimeAdvertisement(b"\x00" * 5)
    assert adv.Active is False
    adv.Active = True
    assert adv.Active is True
    adv.Active = False
    assert adv.Active is False


def test_tx_power_property_is_writable():
    # BlueZ writes back the negotiated TxPower once per second while a
    # window is open; without a writable backing field dbus-next rejects
    # the Set as "the property is readonly".
    adv = TimeAdvertisement(b"\x00" * 5)
    assert adv.TxPower == 0
    adv.TxPower = -4
    assert adv.TxPower == -4


def test_service_data_reflects_payload():
    adv = TimeAdvertisement(build_payload(0xDEADBEEF))
    variants = adv.ServiceData
    assert SERVICE_UUID in variants
    assert bytes(variants[SERVICE_UUID].value) == bytes.fromhex("efbeadde00")


async def test_update_payload_registers_once_then_emits(monkeypatch):
    # Cycling RegisterAdvertisement on every payload change broke Realtek
    # controllers in the field; verify we register once and refresh data
    # via PropertiesChanged for subsequent updates.
    fake_manager = MagicMock()
    fake_manager.call_register_advertisement = AsyncMock()
    fake_manager.call_unregister_advertisement = AsyncMock()
    fake_inner = MagicMock()
    fake_inner.set_payload = MagicMock()
    fake_inner.emit_properties_changed = MagicMock()

    async def _stub_connect(self):
        self._manager = fake_manager
        self._adv = fake_inner
        return fake_manager

    monkeypatch.setattr(Advertiser, "_ensure_connected", _stub_connect)

    adv = Advertiser()
    await adv.update_payload(b"\x01\x00\x00\x00\x00")
    await adv.update_payload(b"\x02\x00\x00\x00\x00")
    await adv.update_payload(b"\x02\x00\x00\x00\x00")  # no-op (same bytes)
    await adv.update_payload(b"\x03\x00\x00\x00\x00")

    assert fake_manager.call_register_advertisement.await_count == 1
    assert fake_manager.call_unregister_advertisement.await_count == 0
    # 2nd and 4th calls change payload; 3rd is a no-op.
    assert fake_inner.emit_properties_changed.call_count == 2
