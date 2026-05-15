"""Cross-check against ble-clock's test_time_adv.c known vectors."""

from __future__ import annotations

import pytest

from ble_clock_beacon.protocol import build_payload


def test_payload_zero():
    assert build_payload(0) == bytes.fromhex("0000000000")


def test_payload_deadbeef_matches_firmware_vector():
    # ble-clock/main/test_time_adv.c uses 0xDEADBEEF with flag 0x00.
    assert build_payload(0xDEADBEEF) == bytes.fromhex("efbeadde00")


def test_payload_max_uint32():
    assert build_payload(0xFFFFFFFF) == bytes.fromhex("ffffffff00")


def test_payload_with_flag():
    assert build_payload(0x01020304, 0x42) == bytes.fromhex("0403020142")


def test_payload_rejects_overflow():
    with pytest.raises(ValueError):
        build_payload(0x1_0000_0000)


def test_payload_rejects_negative():
    with pytest.raises(ValueError):
        build_payload(-1)


def test_payload_rejects_bad_flag():
    with pytest.raises(ValueError):
        build_payload(0, 0x100)
