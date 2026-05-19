# ble-clock-beacon

A small Linux daemon that broadcasts the current UNIX time over BLE for the
[ble-clock](https://github.com/hideosasaki/ble-clock) low-power analog wall clock.

The clock side runs on a battery-powered ESP32 and wakes every 15 minutes to
listen for a 60-second advertising burst from the host running this daemon.
The host is the authoritative time source (NTP-synced) and the clock simply
nudges its hands to match. The daemon runs equally well under systemd (Pi OS,
Debian, Ubuntu) and on non-systemd hosts (OpenWrt, busybox, Alpine, container
images) — see "Non-systemd hosts" and "Running in Docker" below.

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

- Linux with **BlueZ ≥ 5.50** exposing `org.bluez.LEAdvertisingManager1`
  on the **DBus system bus** (this is the default BlueZ build; nothing
  to configure on Pi OS / Debian / Ubuntu / OpenWrt 23.05+)
- A BLE controller in peripheral role (`bluetoothctl show` reporting
  `Roles: peripheral` and `Powered: yes`)
- Python ≥ 3.10
- An NTP client driving the kernel clock (`systemd-timesyncd`,
  `chrony`, busybox `ntpd`, ...). See "Non-systemd hosts" if your host
  has no `timedatectl`.
- The daemon must be a member of the `bluetooth` group, or run as
  root. See "Running in Docker" for the container case.

## Non-systemd hosts

The daemon picks an NTP-ready signal in this priority order:

1. `BLE_BEACON_NTP_READY_FILE` (env var) — if set, the daemon blocks
   until that path exists. This is the opt-in escape hatch.
2. `timedatectl show -p NTPSynchronized --value == "yes"` — used
   automatically when `timedatectl` is on `PATH`.
3. `adjtimex(2)` syscall — fallback that works with `chrony`, full
   `ntpd`, and most other NTP clients.

**Busybox `ntpd` users must set `BLE_BEACON_NTP_READY_FILE`.** Busybox
never clears `STA_UNSYNC` in the kernel timex state, so `adjtimex` is
unusable on those hosts and the daemon would block on startup
forever.

Minimal recipe on a busybox host (creates the flag on the first
stratum/step event from the NTP client):

```sh
# /etc/hotplug.d/ntp/30-ntp-synced
#!/bin/sh
[ "$ACTION" = stratum ] || [ "$ACTION" = step ] || exit 0
touch /var/run/ntp.synced
```

Then run the daemon with `BLE_BEACON_NTP_READY_FILE=/var/run/ntp.synced`.

## Running in Docker

BlueZ's DBus API and the kernel's HCI socket are both host-scoped, so
the container must share the host's network and DBus namespaces:

- `network_mode: host` — required. BlueZ talks to the kernel via
  `AF_BLUETOOTH` sockets, which are tied to the host network
  namespace.
- Bind-mount `/var/run/dbus` so the container reaches the system bus.
- **Run the container as root.** DBus on BlueZ uses EXTERNAL auth,
  which matches by UID; a non-root container UID will not match any
  policy rule for `org.bluez` and authentication fails silently before
  the advertiser even tries to register.

Minimal `docker-compose.yml`:

```yaml
services:
  ble-clock-beacon:
    image: ble-clock-beacon:latest
    network_mode: host
    user: "0:0"
    volumes:
      - /var/run/dbus:/var/run/dbus
    environment:
      # Only needed on busybox-ntpd hosts; harmless otherwise.
      BLE_BEACON_NTP_READY_FILE: /var/run/ntp.synced
    restart: unless-stopped
```

If using the flag-file path, also bind-mount the directory containing
the flag (e.g. `/var/run:/var/run`) so the container can see when the
host's NTP client touches it.

## Install

On a systemd host:

```sh
python3 -m venv /opt/ble-clock-beacon/.venv
/opt/ble-clock-beacon/.venv/bin/pip install .
sudo cp systemd/ble-clock-beacon.service /etc/systemd/system/
sudo systemctl daemon-reload
sudo systemctl enable --now ble-clock-beacon
```

Adjust `ExecStart` in the unit file to point at the venv's
`ble-clock-beacon` entrypoint.

On non-systemd hosts, run the `ble-clock-beacon` entrypoint directly
under whatever supervisor the host provides (procd, OpenRC, runit, the
Docker container's PID 1, ...). The daemon has no init-system
dependencies of its own.

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
