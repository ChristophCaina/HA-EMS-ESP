# Manual test cases: value sync & write paths

These cover the REST/MQTT value-preservation fix and the general write
behavior for dynamic entities (`number`, `switch`, `text`). Run after any
change to `coordinator.py`, `mqtt.py`, or `dynamic_entity.py`.

Prerequisites: a writeable test entity that has no reliable `value` field
in the REST bulk listing (e.g. a Custom Entity RAM value) is the most
sensitive case — prefer it over `analogsensor`/`temperaturesensor` entities
for these tests, since those *do* report `value` via REST and would mask
the bug this fix addresses.

## TC1 — Valid write from Home Assistant

1. Set a valid value on the entity from HA (matching its expected format,
   e.g. a number for a °C-tagged text entity).
2. **Expected:** value appears immediately in HA (optimistic update), and
   is visible on the EMS-ESP web UI / REST (`/api/<device>/<entity>`)
   shortly after (depends on write path: REST is near-instant, MQTT-only
   depends on the gateway picking up the command topic).
3. Wait for the next structure poll (or trigger a reload).
4. **Expected:** value in HA still matches — the REST poll must not
   overwrite it with something else or clear it.

## TC2 — Invalid or empty value

1. Attempt to set a non-numeric value on a unit-tagged `text` entity (or
   clear the field).
2. **Expected:** HA rejects the write client-side (red outline) and/or
   raises an error — no command is sent to EMS-ESP.
3. **Expected:** the entity's displayed value stays at its last known
   real value (from EMS-ESP) — it must NOT go blank/"Unknown" as a side
   effect of the rejected write.

## TC3 — MQTT disabled on the gateway

1. With a known-good value showing in HA, disable MQTT on the EMS-ESP
   gateway (Settings → MQTT → deaktivieren).
2. Wait at least one full structure-poll interval
   (`CONF_STRUCTURE_SCAN_INTERVAL`, default 300s).
3. **Expected:** the value in HA stays stable at the last known value —
   it must not go blank just because REST polling continues without MQTT
   backing it up.
4. **Expected (separately, Repairs):** after the configured MQTT heartbeat
   timeout, a "MQTT live updates unavailable" repair issue should appear
   (see main README, Troubleshooting section) — this is a different
   mechanism than the value itself, don't conflate the two.

## TC4 — MQTT re-enabled after TC3

1. Re-enable MQTT on the gateway.
2. Change the value directly on the EMS-ESP web UI (not via HA).
3. **Expected:** HA picks up the new value via the `<base>/<device>_data`
   MQTT push, without needing a manual reload.
4. Wait for the next structure poll to also occur.
5. **Expected:** the REST poll does not revert the value back to
   whatever it last knew — the MQTT-pushed value must persist.

## TC5 — Custom Entity removed on the gateway

*(Requires the dynamic entity/device removal feature — see "Custom
Entities werden entfernt" in the project notes.)*

1. Create a Custom Entity (RAM or NVS value) on the gateway, confirm it
   shows up in HA as its own device ("Custom Entities") linked via
   `via_device` to the gateway.
2. Delete the Custom Entity on the gateway.
3. Wait for the next structure poll.
4. **Expected:** the corresponding HA entity is removed from the entity
   registry (not just marked unavailable forever).
5. If that was the last entity on the "Custom Entities" device:
   **Expected:** the device itself is also removed automatically.
6. **Expected throughout:** the EMS-ESP Gateway device itself is never
   affected by this cleanup, regardless of what happens to other devices.
