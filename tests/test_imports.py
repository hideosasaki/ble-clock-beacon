"""Import-time smoke tests.

`advertiser.py` builds a dbus-next interface class at import time. The
`@method` / `@dbus_property` decorators inspect the return annotations
and reject any non-literal (e.g. anything PEP 563 has deferred to a
string). A bare `import` is enough to catch a regression like
``from __future__ import annotations`` being re-added to that module.
"""

from __future__ import annotations


def test_advertiser_imports():
    import ble_clock_beacon.advertiser  # noqa: F401


def test_daemon_imports():
    import ble_clock_beacon.daemon  # noqa: F401


def test_advertisement_instantiates():
    # Catches class-creation-time failures dbus-next defers to __init__,
    # e.g. properties missing a setter when access defaults to read-write.
    from ble_clock_beacon.advertiser import TimeAdvertisement

    TimeAdvertisement(b"\x00" * 5)
