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
- <base>/status - Online/Offline (LWT). Loest bei einem Statuswechsel einen
  sofortigen REST-Refresh beider Coordinators aus (Verfuegbarkeit haengt
  ausschliesslich an REST, siehe coordinator.py) und aktualisiert direkt
  den "mqtt_unavailable" Repair-Hinweis.
- <base>/heartbeat - periodisches Diagnose-Kompaktformat (siehe
  _apply_heartbeat_overlay fuer die gemappten Felder). Wird ZUSAETZLICH
  als Watchdog-Signal genutzt: bleibt er zu lange aus, gilt MQTT als
  ausgefallen (siehe _check_heartbeat_timeout). Das ist noetig, weil ein
  *sauberes* Deaktivieren von MQTT auf dem Gateway oft KEIN Last-Will
  "offline" ausloest - das MQTT-Protokoll feuert den Will nur bei einem
  *unsauberen* Verbindungsabbruch (Timeout etc.), nicht bei einem
  ordentlichen DISCONNECT. Der reine status-Topic allein waere in diesem
  Fall also blind.
- <base>/info - einmalig beim Boot gesendet. Liefert "bootTime" (absoluter
  Zeitstempel), den REST gar nicht hat.

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
from datetime import timedelta
from typing import Any

from homeassistant.components import mqtt
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant, callback
from homeassistant.exceptions import HomeAssistantError
from homeassistant.helpers import issue_registry as ir
from homeassistant.helpers.event import async_track_time_interval
from homeassistant.util import dt as dt_util
from homeassistant.util.json import json_loads

from .const import CONF_MQTT_BASE_TOPIC, DEFAULT_MQTT_BASE_TOPIC, DOMAIN
from .coordinator import EmsEspStructureCoordinator, EmsEspSystemCoordinator
from .issues import mqtt_unavailable_issue_id

_LOGGER = logging.getLogger(__name__)

_VALUE_FIELDS = ("value", "temp")
_DATA_TOPIC_SUFFIX = "_data"
_STATUS_SUBTOPIC = "status"
_HEARTBEAT_SUBTOPIC = "heartbeat"
_INFO_SUBTOPIC = "info"

# ~2,5x der EMS-ESP Standard-Heartbeat-Periode (60s) - toleriert einen
# einzelnen ausgefallenen Heartbeat plus etwas Jitter, bevor MQTT als
# ausgefallen gilt. Nicht dynamisch aus mqtt.publishTimeHeartbeat
# abgeleitet (waere praeziser, aber mehr Komplexitaet fuer wenig Nutzen).
_HEARTBEAT_TIMEOUT = timedelta(seconds=150)
_WATCHDOG_INTERVAL = timedelta(seconds=30)


def _extract_value(item: dict[str, Any]) -> Any:
    for field in _VALUE_FIELDS:
        if field in item:
            return item[field]
    return None


def _apply_heartbeat_overlay(
    coordinator: EmsEspSystemCoordinator, heartbeat: dict[str, Any]
) -> None:
    """Schreibt ausgewaehlte, eindeutig zuordenbare Heartbeat-Felder ins Overlay.

    coordinator.mqtt_overlay ist persistent (siehe coordinator.py) - anders
    als self.data wird es NICHT durch den naechsten REST-Poll ueberschrieben.
    """
    overlay = coordinator.mqtt_overlay
    system = overlay.setdefault("system", {})
    bus = overlay.setdefault("bus", {})
    api = overlay.setdefault("api", {})
    mqtt_section = overlay.setdefault("mqtt", {})

    if "uptime" in heartbeat:
        system["uptime"] = heartbeat["uptime"]
    if "uptime_sec" in heartbeat:
        system["uptimeSec"] = heartbeat["uptime_sec"]
    if "freemem" in heartbeat:
        system["freeMem"] = heartbeat["freemem"]
    if "bus_status" in heartbeat:
        bus["busStatus"] = heartbeat["bus_status"]
    if "apicalls" in heartbeat:
        api["APICalls"] = heartbeat["apicalls"]
    if "apifails" in heartbeat:
        api["APIFails"] = heartbeat["apifails"]
    if "mqttcount" in heartbeat:
        mqtt_section["messagesSent"] = heartbeat["mqttcount"]
    if "mqttfails" in heartbeat:
        mqtt_section["messageFails"] = heartbeat["mqttfails"]


def _apply_info_overlay(coordinator: EmsEspSystemCoordinator, info: dict[str, Any]) -> None:
    """Schreibt bootTime aus dem einmaligen Boot-Info-Topic ins Overlay."""
    if "bootTime" in info:
        coordinator.mqtt_overlay.setdefault("system", {})["bootTime"] = info["bootTime"]


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
    """Abonniert <base>/+, aktualisiert den Struktur-Coordinator live und
    ueberwacht laufend, ob MQTT-Daten noch ankommen (Repair-Issue).

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
    issue_id = mqtt_unavailable_issue_id(entry)

    # Geteilter veraenderlicher Zustand zwischen Message-Handler und
    # Watchdog-Timer (Closure-Variablen, wie schon bei
    # dynamic_entity.async_setup_dynamic_platform).
    state: dict[str, Any] = {"last_heartbeat_at": None, "issue_active": False}

    def _mark_mqtt_ok() -> None:
        if state["issue_active"]:
            ir.async_delete_issue(hass, DOMAIN, issue_id)
            state["issue_active"] = False

    def _mark_mqtt_unavailable() -> None:
        if not state["issue_active"]:
            ir.async_create_issue(
                hass,
                DOMAIN,
                issue_id,
                is_fixable=False,
                severity=ir.IssueSeverity.WARNING,
                translation_key="mqtt_unavailable",
                translation_placeholders={"title": entry.title},
            )
            state["issue_active"] = True

    @callback
    def _handle_message(msg: mqtt.ReceiveMessage) -> None:
        if not msg.topic.startswith(f"{base_topic}/"):
            return
        subtopic = msg.topic[len(base_topic) + 1 :]

        if subtopic == _STATUS_SUBTOPIC:
            is_online = str(msg.payload).strip().lower() == "online"
            _LOGGER.debug("EMS-ESP MQTT status: %s (online=%s)", msg.payload, is_online)
            if is_online:
                _mark_mqtt_ok()
            else:
                _mark_mqtt_unavailable()
            # Verfuegbarkeit der Entities haengt ausschliesslich an REST
            # (siehe coordinator.py) - hier nur ein sofortiger Anstoss,
            # damit ein echter Ausfall schneller auffaellt als beim
            # naechsten planmaessigen Poll.
            hass.async_create_task(structure_coordinator.async_request_refresh())
            hass.async_create_task(system_coordinator.async_request_refresh())
            return

        if subtopic == _HEARTBEAT_SUBTOPIC:
            state["last_heartbeat_at"] = dt_util.utcnow()
            _mark_mqtt_ok()
            try:
                payload = json_loads(msg.payload)
            except ValueError:
                _LOGGER.debug("Ungueltiges JSON auf %s: %s", msg.topic, msg.payload)
                return
            if isinstance(payload, dict):
                _apply_heartbeat_overlay(system_coordinator, payload)
                system_coordinator.async_update_listeners()
            return

        if subtopic == _INFO_SUBTOPIC:
            try:
                payload = json_loads(msg.payload)
            except ValueError:
                _LOGGER.debug("Ungueltiges JSON auf %s: %s", msg.topic, msg.payload)
                return
            if isinstance(payload, dict):
                _apply_info_overlay(system_coordinator, payload)
                system_coordinator.async_update_listeners()
            return

        if not subtopic.endswith(_DATA_TOPIC_SUFFIX):
            return  # sonstige, (noch) nicht ausgewertete Topics

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

    @callback
    def _check_heartbeat_timeout(_now) -> None:
        last = state["last_heartbeat_at"]
        if last is None:
            return  # noch nie einen Heartbeat gesehen - keine Aussage moeglich
        if dt_util.utcnow() - last > _HEARTBEAT_TIMEOUT:
            _LOGGER.debug(
                "Kein EMS-ESP MQTT heartbeat mehr seit %s - markiere MQTT als nicht verfuegbar",
                last,
            )
            _mark_mqtt_unavailable()

    unsubscribe = await mqtt.async_subscribe(hass, subscribe_topic, _handle_message, qos=0)
    entry.async_on_unload(unsubscribe)
    entry.async_on_unload(
        async_track_time_interval(hass, _check_heartbeat_timeout, _WATCHDOG_INTERVAL)
    )
    _LOGGER.debug("EMS-ESP MQTT Live-Updates abonniert auf %s", subscribe_topic)
