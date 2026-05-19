# ble-clock-beacon

A small systemd daemon that broadcasts the current UNIX time over BLE for the
[ble-clock](https://github.com/hideosasaki/ble-clock) low-power analog wall clock.

The clock side runs on a battery-powered ESP32 and wakes every 15 minutes to
listen for a 60-second advertising burst from the Raspberry Pi running this
daemon. The Pi side is the authoritative time source (NTP-synced) and the
clock simply nudges its hands to match.

## Wire format

- AD type `0x21` (Service Data - 128-bit UUID)
- Service UUID: `74F6FB5B-EF7A-4A08-8F3E-A6C2BDFF2010`
- 5-byte payload:
  - bytes 0..3 — UNIX seconds (UTC), little-endian uint32
  - byte 4 — command flag (always `0x00` today, reserved)
- Non-connectable, non-scannable, 100 ms advertising interval, channels 37/38/39

The clock firmware parses these frames in
[`main/time_adv.c`](https://github.com/hideosasaki/ble-clock/blob/main/main/time_adv.c);
the unit tests in `tests/test_protocol.py` here use the same `0xDEADBEEF`
vector as the firmware tests to guarantee bit-exact compatibility.

## Transmit schedule

Four 60-second windows per hour, centered on the clock's wake-up moments
(HH:00, :15, :30, :45) with a ±30 s margin:

```
HH:59:30 .. HH+1:00:30
HH:14:30 .. HH:15:30
HH:29:30 .. HH:30:30
HH:44:30 .. HH:45:30
```

That works out to ~4 minutes of advertising per hour; the rest of the time
the radio is idle.

## Requirements

- Linux with BlueZ ≥ 5.50 (Raspberry Pi OS Bookworm is fine)
- Python ≥ 3.10
- An NTP client driving the kernel clock (`systemd-timesyncd`, `chrony`,
  busybox `ntpd`, ...). Non-systemd hosts (e.g. OpenWrt) are supported
  via an `adjtimex(2)` fallback in `ntp.py`. Busybox `ntpd` never
  clears `STA_UNSYNC`, so on OpenWrt set `BLE_BEACON_NTP_READY_FILE`
  to a path that the system touches once NTP is in sync (e.g. from
  `/etc/hotplug.d/ntp/30-ntp-synced` on `ACTION=stratum`); the daemon
  will then block on that file instead of `timedatectl`/`adjtimex`.
- User in the `bluetooth` group, or root

## Install

```sh
python3 -m venv /opt/ble-clock-beacon/.venv
/opt/ble-clock-beacon/.venv/bin/pip install .
sudo cp systemd/ble-clock-beacon.service /etc/systemd/system/
sudo systemctl daemon-reload
sudo systemctl enable --now ble-clock-beacon
```

Adjust `ExecStart` in the unit file to point at the venv's
`ble-clock-beacon` entrypoint.

## Verify

In one terminal:

```sh
sudo btmon | grep -A2 -i 'service data'
```

You should see `0x21` service-data frames carrying the UUID above only during
the transmit windows; the rest of the hour, no frames from this host.

## Development

```sh
python3 -m venv .venv
. .venv/bin/activate
pip install -e '.[dev]'
pytest
```

The unit tests are pure-Python and run on any platform; the DBus advertiser
needs an actual BlueZ host.
