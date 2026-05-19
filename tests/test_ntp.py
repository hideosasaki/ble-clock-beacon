"""Tests for the NTP-sync probe.

Two backends, exercised independently:

- ``_check_timedatectl`` parses ``timedatectl show -p NTPSynchronized``
- ``_check_adjtimex`` invokes the cached ``adjtimex(2)`` function pointer
  and reads the return code plus the ``STA_UNSYNC`` status bit

``is_ntp_synchronized`` dispatches on the cached ``_TIMEDATECTL`` path.
Both backends and the dispatch are mocked so the suite runs on any host
(incl. macOS, which has no ``adjtimex`` syscall).
"""

from __future__ import annotations

import subprocess
from unittest.mock import MagicMock

import pytest

from ble_clock_beacon import ntp
from ble_clock_beacon.ntp import (
    STA_UNSYNC,
    TIME_ERROR,
    _check_adjtimex,
    _check_timedatectl,
    is_ntp_synchronized,
)


def _fake_run(stdout: str):
    def _run(*_args, **_kwargs):
        result = MagicMock()
        result.stdout = stdout
        return result

    return _run


def test_timedatectl_yes(monkeypatch):
    monkeypatch.setattr(ntp.subprocess, "run", _fake_run("yes\n"))
    assert _check_timedatectl() is True


def test_timedatectl_no(monkeypatch):
    monkeypatch.setattr(ntp.subprocess, "run", _fake_run("no\n"))
    assert _check_timedatectl() is False


@pytest.mark.parametrize(
    "exc",
    [
        FileNotFoundError("timedatectl missing"),
        subprocess.CalledProcessError(1, "timedatectl"),
        subprocess.TimeoutExpired("timedatectl", 5),
    ],
)
def test_timedatectl_exceptions_return_false(monkeypatch, exc):
    def _raise(*_args, **_kwargs):
        raise exc

    monkeypatch.setattr(ntp.subprocess, "run", _raise)
    assert _check_timedatectl() is False


def _install_fake_adjtimex(monkeypatch, rc: int, status: int):
    def _adjtimex(tx_ref):
        tx_ref._obj.status = status
        return rc

    monkeypatch.setattr(ntp, "_ADJTIMEX", _adjtimex)


def test_adjtimex_happy(monkeypatch):
    _install_fake_adjtimex(monkeypatch, rc=0, status=0)
    assert _check_adjtimex() is True


def test_adjtimex_returns_time_error(monkeypatch):
    _install_fake_adjtimex(monkeypatch, rc=TIME_ERROR, status=0)
    assert _check_adjtimex() is False


def test_adjtimex_negative_rc(monkeypatch):
    _install_fake_adjtimex(monkeypatch, rc=-1, status=0)
    assert _check_adjtimex() is False


def test_adjtimex_unsync_bit_set(monkeypatch):
    _install_fake_adjtimex(monkeypatch, rc=0, status=STA_UNSYNC)
    assert _check_adjtimex() is False


def test_adjtimex_unavailable(monkeypatch):
    monkeypatch.setattr(ntp, "_ADJTIMEX", None)
    assert _check_adjtimex() is False


def test_dispatch_uses_timedatectl_when_present(monkeypatch):
    monkeypatch.setattr(ntp, "_TIMEDATECTL", "/usr/bin/timedatectl")
    monkeypatch.setattr(ntp, "_check_timedatectl", lambda: True)
    monkeypatch.setattr(
        ntp,
        "_check_adjtimex",
        lambda: pytest.fail("adjtimex must not be called when timedatectl is on PATH"),
    )
    assert is_ntp_synchronized() is True


def test_dispatch_falls_back_to_adjtimex(monkeypatch):
    monkeypatch.setattr(ntp, "_TIMEDATECTL", None)
    monkeypatch.setattr(
        ntp,
        "_check_timedatectl",
        lambda: pytest.fail("timedatectl must not be called when not on PATH"),
    )
    monkeypatch.setattr(ntp, "_check_adjtimex", lambda: True)
    assert is_ntp_synchronized() is True
