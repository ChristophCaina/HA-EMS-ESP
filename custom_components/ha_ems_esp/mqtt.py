"""MQTT-Live-Push und Kommando-Publish fuer ha_ems_esp.

Aktualisiert die Werte im bereits bestehenden EmsEspStructureCoordinator
per MQTT-Push, statt auf den naechsten REST-Poll (alle
DEFAULT_STRUCTURE_SCAN_INTERVAL Sekunden) zu warten. Nutzt HA's eigene
MQTT-Integration (kein eigener Broker-Client - siehe manifest.json
Dependency "mqtt").

Abgedeckte Topics (bestaetigt gegen echte Payloads von analogsensor/
temperaturesensor):
- <base>/<device_type>_data - die eigentlichen Werte. Jeder Eintrag im
  Payload hat ein "name"-Feld, das den REST-Entity-Key matcht (der
  aeussere Payload-Key ist z.B. GPIO-Nummer oder 1-Wire-ID, NICHT der
  Name). Das Wertfeld heisst je nach Geraetetyp "value" oder "temp"
  (z.B. bei temperaturesensor) - beides wird abgedeckt.
- <base>/status - Online/Offline (LWT). Wird aktuell nur geloggt, noch
  nicht mit der Entity-Verfuegbarkeit verdrahtet (TODO fuer spaeter).

NICHT abgedeckt (bewusst): <base>/heartbeat und <base>/info - anderes
Feldschema als /api/system/info (z.B. "bus_status" statt "busStatus",
kein "model"), wuerden ein eigenes Mapping brauchen. Diagnose-Werte
bleiben deshalb vorerst REST-basiert (EmsEspSystemCoordinator).

Kommando-Schreibpfad (async_publish_command): bestaetigt gegen die
offizielle EMS-ESP Commands-Referenz (emsesp.org/Commands) - ANDERES
Format als der REST-Schreibpfad! Kein Command im Topic-Pfad, sondern:
    Topic:   <base>/<device_type>
    Payload: {"entity": "<entity_key>", "value": <wert>}
("entity" ist ein Alias fuer "cmd", "value" ein Alias fuer "data" - beide
Schreibweisen sind laut Doku gleichwertig akzeptiert). Wird NIE retained
publiziert - ein retained Kommando wuerde bei jedem Reconnect/Resubscribe
erneut ausgefuehrt werden, das waere gefaehrlich.
"""
from __future__ import annotations

import json
import logging
from typing import Any

from homeassistant.components import mqtt
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant, callback
from homeassistant.exceptions import HomeAssistantError
from homeassistant.util.json import json_loads

from .const import CONF_MQTT_BASE_TOPIC, DEFAULT_MQTT_BASE_TOPIC, DOMAIN
from .coordinator import EmsEspStructureCoordinator, EmsEspSystemCoordinator

_LOGGER = logging.getLogger(__name__)

_VALUE_FIELDS = ("value", "temp")
_DATA_TOPIC_SUFFIX = "_data"
_STATUS_SUBTOPIC = "status"


def _extract_value(item: dict[str, Any]) -> Any:
    for field in _VALUE_FIELDS:
        if field in item:
            return item[field]
    return None


async def async_publish_command(
    hass: HomeAssistant,
    entry: ConfigEntry,
    device_type: str,
    entity_key: str,
    value: Any,
) -> None:
    """Publiziert ein Kommando per MQTT (siehe Modul-Docstring fuer das Format)."""
    base_topic = entry.options.get(CONF_MQTT_BASE_TOPIC, DEFAULT_MQTT_BASE_TOPIC)
    topic = f"{base_topic}/{device_type}"
    payload = json.dumps({"entity": entity_key, "value": value})
    try:
        await mqtt.async_publish(hass, topic, payload, qos=0, retain=False)
    except HomeAssistantError:
        raise
    except Exception as err:  # noqa: BLE001 - z.B. MQTT-Integration nicht verbunden
        raise HomeAssistantError(f"MQTT-Publish auf {topic} fehlgeschlagen") from err


async def async_setup_mqtt_listener(hass: HomeAssistant, entry: ConfigEntry) -> None:
    """Abonniert <base>/+ und aktualisiert den Struktur-Coordinator live.

    Best-effort: Wenn HA's MQTT-Integration nicht konfiguriert/verbunden
    ist, schlaegt das Subscribe fehl - das wird vom Aufrufer (__init__.py)
    abgefangen, damit der Rest der Integration (REST-basiert) unabhaengig
    davon funktioniert.
    """
    data = hass.data[DOMAIN][entry.entry_id]
    structure_coordinator: EmsEspStructureCoordinator = data["structure_coordinator"]
    system_coordinator: EmsEspSystemCoordinator = data["system_coordinator"]
    base_topic = entry.options.get(CONF_MQTT_BASE_TOPIC, DEFAULT_MQTT_BASE_TOPIC)
    subscribe_topic = f"{base_topic}/+"

    @callback
    def _handle_message(msg: mqtt.ReceiveMessage) -> None:
        if not msg.topic.startswith(f"{base_topic}/"):
            return
        subtopic = msg.topic[len(base_topic) + 1 :]

        if subtopic == _STATUS_SUBTOPIC:
            is_available = str(msg.payload).strip().lower() == "online"
            _LOGGER.debug("EMS-ESP MQTT status: %s -> available=%s", msg.payload, is_available)
            structure_coordinator.mqtt_available = is_available
            system_coordinator.mqtt_available = is_available
            structure_coordinator.async_update_listeners()
            system_coordinator.async_update_listeners()
            return

        if not subtopic.endswith(_DATA_TOPIC_SUFFIX):
            return  # z.B. heartbeat/info - siehe Modul-Docstring

        device_type = subtopic[: -len(_DATA_TOPIC_SUFFIX)]

        try:
            payload = json_loads(msg.payload)
        except ValueError:
            _LOGGER.debug("Ungueltiges JSON auf %s: %s", msg.topic, msg.payload)
            return
        if not isinstance(payload, dict):
            return

        current = structure_coordinator.data or {}
        entities = current.get(device_type)
        if entities is None:
            # Geraetetyp der REST-Struktur-Discovery noch nicht bekannt -
            # der naechste Struktur-Poll holt das automatisch nach.
            return

        updated_entities = [dict(entity) for entity in entities]
        changed = False
        for item in payload.values():
            if not isinstance(item, dict):
                continue
            name = item.get("name")
            if not name:
                continue
            value = _extract_value(item)
            for entity in updated_entities:
                if entity.get("name") == name and entity.get("value") != value:
                    entity["value"] = value
                    changed = True
                    break

        if changed:
            new_data = dict(current)
            new_data[device_type] = updated_entities
            structure_coordinator.async_set_updated_data(new_data)

    unsubscribe = await mqtt.async_subscribe(hass, subscribe_topic, _handle_message, qos=0)
    entry.async_on_unload(unsubscribe)
    _LOGGER.debug("EMS-ESP MQTT Live-Updates abonniert auf %s", subscribe_topic)
