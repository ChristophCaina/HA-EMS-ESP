# HA-EMS-ESP

A custom Home Assistant integration for [EMS-ESP32](https://github.com/emsesp/EMS-ESP32) gateways (e.g. [BBQKees Electronics](https://bbqkees-electronics.nl) boards) that read and control EMS/Heatronic-compatible heating equipment — boilers, heat pumps, thermostats, solar modules, and more.

> **Status: early / actively developed.** So far this has only been tested against a gateway with no EMS bus device attached yet (only the gateway's own internal sensors — Dallas temperature probe, analog inputs, status LED). Entity creation for real EMS devices (boiler, heat pump, thermostat, ...) is built generically and *should* work, but is not yet verified against real hardware. Feedback and issue reports are very welcome.

## Why this integration

EMS-ESP already has excellent built-in MQTT Discovery support for Home Assistant. This integration takes a different approach:

- **REST-driven structure discovery** — entities are created dynamically from the gateway's own `/api/<device>/entities` responses, so new devices, entities, or firmware-added fields show up automatically without reconfiguring anything.
- **MQTT for live values** — once structure is known via REST, value updates are pushed live over MQTT instead of being polled, without needing MQTT Discovery to be enabled on the gateway (and without colliding with Home Assistant's own native MQTT integration).
- **Both REST and MQTT as write paths** — commands can be sent either way, or both for redundancy.
- **A real Home Assistant device tree** — the gateway itself is a device, and every EMS bus device gets its own device, linked via `via_device`.

## Features

- Zeroconf auto-discovery of EMS-ESP gateways on the local network
- Config flow validates connectivity via `/api/system/info` before setup
- Dynamic entity creation (`sensor`, `binary_sensor`, `number`, `switch`) from `/api/<device>/entities`, with automatic platform selection based on the API's reported `type` and `writeable` flag
- Device classes and units inferred automatically from the API's reported unit of measurement
- Gateway modeled as its own device with ~25 diagnostic sensors (uptime, memory, bus quality, API/MQTT counters, AP fallback status, boot time, and more)
- MQTT live-value push (`<base>/<device>_data` topics) — updates arrive in real time instead of waiting for the next REST poll
- MQTT heartbeat/info topics feed additional gateway diagnostics (boot time, MQTT message counters) that REST alone doesn't expose
- Configurable command write path: REST, MQTT, or both
- Optimistic local state updates after a write (no UI flicker while waiting for confirmation)
- Home Assistant [Repairs](https://www.home-assistant.io/integrations/repairs/) integration: surfaces "MQTT unavailable" and "gateway unreachable" issues in the UI instead of silent log warnings, with a heartbeat watchdog that also catches a *clean* MQTT disconnect (which doesn't always trigger the standard MQTT Last Will message)
- Informational firmware update check against the latest stable [EMS-ESP32 GitHub release](https://github.com/emsesp/EMS-ESP32/releases) (pre-releases/dev builds are excluded automatically)

## Requirements

- Home Assistant 2024.x or newer
- An EMS-ESP32 gateway (e.g. a BBQKees board) reachable over HTTP on your local network
- Home Assistant's own MQTT integration configured and connected to the same broker as your EMS-ESP gateway, if you want live updates and MQTT-based commands (optional — the integration works over REST-only too, just with slower, polled updates)
- If EMS-ESP's "Bypass Access Token authorization on API calls" setting is **off** (the default, and the recommended setting): an Access Token from the EMS-ESP web UI (Settings → Security → Manage Users → key icon) for command write access. Read-only access never requires a token.

## Installation

### HACS (recommended)

1. HACS → Integrations → ⋮ → Custom repositories → add this repository URL, category "Integration"
2. Install "EMS-ESP (Custom)"
3. Restart Home Assistant

### Manual

1. Copy the `custom_components/ha_ems_esp` folder into your Home Assistant `custom_components` directory
2. Restart Home Assistant

## Configuration

Configuration is done entirely through the UI (Settings → Devices & Services → Add Integration → "EMS-ESP (Custom)"), either triggered automatically via Zeroconf discovery or added manually.

You'll be asked for:

| Field | Notes |
|---|---|
| Host / IP address | The gateway's REST API address. Required. |
| Access token | Optional — only needed for write commands if the gateway requires one. |
| MQTT base topic | Must match the "Base" setting on the gateway's MQTT page. Default `ems-esp`. |
| MQTT discovery enabled / prefix | Reserved for a future MQTT-discovery fallback path; not currently used for anything. |
| Command write path | `rest`, `mqtt`, or `both`. |

All of these except the host can be changed later via the integration's **Options**.

### Recommended MQTT settings on the gateway

- **Retain flag: on** — so retained topics (like `status`, `info`) are delivered immediately on (re)subscribe instead of waiting for the next publish.
- **Clean session: on**
- **Format: nested/embedded in a single topic** (not "individual topics")
- **MQTT Discovery: off** while relying on this integration for structure, or set a **non-default discovery prefix** (not `homeassistant`) if you want to run EMS-ESP's own discovery in parallel without it colliding with Home Assistant's native MQTT integration

## Architecture (brief)

- **REST** (`EmsEspSystemCoordinator`, `EmsEspStructureCoordinator`) is the source of truth for *structure*: which devices exist, which entities they have, their type/writeable/min/max metadata. Polled every 60s (system info) / 5 min (per-device entity lists).
- **MQTT** (`mqtt.py`) pushes *live values* into the already-known structure — no separate value model, it just updates the cached entity dicts the REST layer already built.
- **Gateway-local pseudo-devices** (`temperaturesensor`, `analogsensor` — the gateway's own Dallas probe and analog inputs) are attached to the gateway device itself, not modeled as separate EMS bus devices.
- **Writes** go out over REST-POST and/or MQTT-publish depending on the configured write path, followed by an optimistic local update of the cached value (not a synchronous re-poll, which would race against the MQTT push and cause the UI to flicker back and forth).

## Known limitations

- **`select` for enum-type entities isn't implemented yet.** The `/entities` endpoint reports the current value of an enum entity but not its list of valid options, which `SelectEntity` requires. These currently fall back to a read-only sensor showing the current value. Needs real data from a connected EMS device (or the individual-entity REST endpoint) to finish properly.
- **`climate` for thermostat setpoints isn't implemented yet**, for the same reason — no real thermostat available to test against yet.
- **No automatic firmware flashing.** The `update` entity is informational only (installed vs. latest version, release notes link). EMS-ESP's firmware upload can brick a device if the wrong binary variant is used for the board, and the necessary upload endpoint / board-matching logic hasn't been verified with enough confidence to automate it. Use the EMS-ESP web UI to update firmware manually.
- **`heartbeat`/`info` MQTT topics are only partially mapped.** A few fields (`ntp_status`, `rxfails`/`txreads`/`txwrites`/`txfails`) were deliberately left out because their meaning didn't clearly match the equivalent REST fields when tested.

## Troubleshooting

### Repairs

Settings → System → Repairs will show:

- **MQTT live updates unavailable** — Home Assistant's MQTT integration isn't reachable, or no MQTT traffic has been seen from the gateway recently (heartbeat watchdog, ~2.5 minutes). The integration keeps working over REST regardless; this is informational.
- **Gateway unreachable** — the last REST poll failed. Check that the gateway is powered on and reachable on the network.

Both clear themselves automatically once the underlying problem resolves.

### Debug logging

```yaml
logger:
  default: warning
  logs:
    custom_components.ha_ems_esp: debug
```

## Credits

- [EMS-ESP32](https://github.com/emsesp/EMS-ESP32) — the firmware and REST/MQTT API this integration talks to
- [BBQKees Electronics](https://bbqkees-electronics.nl) — EMS-ESP gateway hardware

## License

See [LICENSE](LICENSE).
