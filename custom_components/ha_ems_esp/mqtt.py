"""MQTT-Live-Push und Kommando-Publish fuer ha_ems_esp.

Aktualisiert die Werte im bereits bestehenden EmsEspStructureCoordinator
per MQTT-Push, statt auf den naechsten REST-Poll (alle
DEFAULT_STRUCTURE_SCAN_INTERVAL Sekunden) zu warten. Nutzt HA's eigene
MQTT-Integration (kein eigener Broker-Client - siehe manifest.json
Dependency "mqtt").

Abgedeckte Topics (bestaetigt gegen echte Payloads von analogsensor/
temperaturesensor):
- <base>/<device_type>_data - die eigentlichen Werte, in ZWEI bestaetigten
  Formen: verschachtelt ({"<gpio/id>": {"name":..., "value"/"temp":...}},
  z.B. bei analogsensor/temperaturesensor) oder FLACH ({"<entity_name>":
  <wert>}, bestaetigt bei custom_data/Custom Entities - dort ist der
  aeussere Key bereits der Entity-Name). Beide werden geparst.
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

from .const import (
    CONF_MQTT_BASE_TOPIC,
    CONF_MQTT_HEARTBEAT_TIMEOUT,
    DEFAULT_MQTT_BASE_TOPIC,
    DEFAULT_MQTT_HEARTBEAT_TIMEOUT,
    DOMAIN,
)
from .coordinator import EmsEspStructureCoordinator, EmsEspSystemCoordinator
from .issues import mqtt_unavailable_issue_id

_LOGGER = logging.getLogger(__name__)

_VALUE_FIELDS = ("value", "temp")
_DATA_TOPIC_SUFFIX = "_data"
_STATUS_SUBTOPIC = "status"
_HEARTBEAT_SUBTOPIC = "heartbeat"
_INFO_SUBTOPIC = "info"

# Watchdog-Poll-Intervall: fest und fein genug, um auch ein kurz
# eingestelltes Timeout (Minimum 30s im Config/Options Flow) noch sinnvoll
# zu erkennen. Das eigentliche Timeout ist konfigurierbar (siehe
# CONF_MQTT_HEARTBEAT_TIMEOUT), Default DEFAULT_MQTT_HEARTBEAT_TIMEOUT.
_WATCHDOG_INTERVAL = timedelta(seconds=15)


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
    heartbeat_timeout = timedelta(
        seconds=entry.options.get(
            CONF_MQTT_HEARTBEAT_TIMEOUT, DEFAULT_MQTT_HEARTBEAT_TIMEOUT
        )
    )

    # Geteilter veraenderlicher Zustand zwischen Message-Handler und
    # Watchdog-Timer (Closure-Variablen, wie schon bei
    # dynamic_entity.async_setup_dynamic_platform). "setup_at" dient als
    # Referenzpunkt, falls NIE ein Heartbeat ankommt (z.B. HA's
    # MQTT-Integration ist deaktiviert, die Subscription haengt einfach
    # folgenlos in der Luft, statt sofort einen Fehler zu werfen) - ohne
    # diesen Fallback haette der Watchdog in diesem Fall nie ausgeloest.
    state: dict[str, Any] = {
        "last_heartbeat_at": None,
        "setup_at": dt_util.utcnow(),
        "issue_active": False,
    }

    def _mark_mqtt_ok() -> None:
        _LOGGER.debug(
            "_mark_mqtt_ok aufgerufen (issue_active vorher=%s)", state["issue_active"]
        )
        if state["issue_active"]:
            ir.async_delete_issue(hass, DOMAIN, issue_id)
            state["issue_active"] = False
            _LOGGER.debug("Repair-Issue %s geloescht", issue_id)

    def _mark_mqtt_unavailable() -> None:
        _LOGGER.debug(
            "_mark_mqtt_unavailable aufgerufen (issue_active vorher=%s)",
            state["issue_active"],
        )
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
            _LOGGER.debug("Repair-Issue %s erstellt", issue_id)

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
            _LOGGER.debug("EMS-ESP MQTT heartbeat empfangen um %s", state["last_heartbeat_at"])
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
        # Zwei bestaetigte Payload-Formen fuer <device>_data:
        # - verschachtelt (analogsensor_data, temperaturesensor_data, ...):
        #   {"<gpio_oder_id>": {"name": "...", "value"/"temp": ...}}
        # - FLACH (bestaetigt bei custom_data): {"<entity_name>": <wert>}
        #   Hier ist der aeussere Key bereits der Entity-Name, der Wert
        #   steht direkt dahinter statt in einem verschachtelten Dict.
        for outer_key, item in payload.items():
            if isinstance(item, dict):
                name = item.get("name")
                if not name:
                    continue
                value = _extract_value(item)
            else:
                name = outer_key
                value = item
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
        reference = state["last_heartbeat_at"] or state["setup_at"]
        elapsed = dt_util.utcnow() - reference
        _LOGGER.debug(
            "MQTT-Watchdog-Check: %.0fs seit letztem Signal (Timeout bei %.0fs), issue_active=%s",
            elapsed.total_seconds(),
            heartbeat_timeout.total_seconds(),
            state["issue_active"],
        )
        if elapsed > heartbeat_timeout:
            _mark_mqtt_unavailable()

    unsubscribe = await mqtt.async_subscribe(hass, subscribe_topic, _handle_message, qos=0)
    entry.async_on_unload(unsubscribe)
    entry.async_on_unload(
        async_track_time_interval(hass, _check_heartbeat_timeout, _WATCHDOG_INTERVAL)
    )
    _LOGGER.debug(
        "EMS-ESP MQTT Live-Updates abonniert auf %s (setup_at=%s, watchdog alle %s, timeout=%s)",
        subscribe_topic,
        state["setup_at"],
        _WATCHDOG_INTERVAL,
        heartbeat_timeout,
    )
