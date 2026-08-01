"""Statische Beschreibung der Gateway-Diagnose-Entities.

Im Gegensatz zu den spaeter dynamisch aus /api/<device>/entities erzeugten
EMS-Geraete-Entities (siehe geplante entity_factory.py) ist die Struktur von
/api/system/info fest im EMS-ESP-Firmware-Schema vorgegeben. Diese Entities
werden deshalb bewusst statisch beschrieben statt dynamisch erzeugt.

Namen werden HART KODIERT (deutsch) statt ueber translation_key aufgeloest:
translation_key fuer Entity-Namen hat sich als unzuverlaessig erwiesen (nur
bei komplettem HA-Neustart zuverlaessig geladen, Ergebnis wird bei
Erst-Registrierung fix in der Entity-Registry gespeichert, aendert sich
danach nicht mehr automatisch - siehe COP-SCOP-Card Erfahrung). Fuer eine
feste, kleine Menge an Diagnose-Entities lohnt sich der Aufwand nicht.

value_fn bekommt jeweils das komplette, verschachtelte system_info-dict aus
EmsEspSystemCoordinator.data.
"""
from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from typing import Any

from homeassistant.components.binary_sensor import BinarySensorDeviceClass
from homeassistant.components.sensor import SensorDeviceClass, SensorStateClass
from homeassistant.const import (
    PERCENTAGE,
    EntityCategory,
    UnitOfInformation,
    UnitOfTime,
)
from homeassistant.util import dt as dt_util


@dataclass(frozen=True, kw_only=True)
class GatewaySensorDescription:
    key: str
    name: str
    value_fn: Callable[[dict[str, Any]], Any]
    icon: str | None = None
    native_unit_of_measurement: str | None = None
    device_class: SensorDeviceClass | None = None
    state_class: SensorStateClass | None = None
    entity_category: EntityCategory | None = EntityCategory.DIAGNOSTIC
    # Manche Werte gibt es nur unter bestimmten Bedingungen (z.B. RSSI nur
    # bei network.network == "WiFi", nicht bei Ethernet). Standardmaessig
    # wird die Entity immer angelegt.
    condition_fn: Callable[[dict[str, Any]], bool] = lambda info: True


@dataclass(frozen=True, kw_only=True)
class GatewayBinarySensorDescription:
    key: str
    name: str
    value_fn: Callable[[dict[str, Any]], bool]
    icon: str | None = None
    device_class: BinarySensorDeviceClass | None = None
    entity_category: EntityCategory | None = EntityCategory.DIAGNOSTIC


GATEWAY_SENSORS: tuple[GatewaySensorDescription, ...] = (
    GatewaySensorDescription(
        key="uptime",
        name="Laufzeit",
        icon="mdi:timer-outline",
        native_unit_of_measurement=UnitOfTime.SECONDS,
        device_class=SensorDeviceClass.DURATION,
        state_class=SensorStateClass.MEASUREMENT,
        entity_category=None,
        value_fn=lambda info: info.get("system", {}).get("uptimeSec"),
    ),
    GatewaySensorDescription(
        key="free_heap",
        name="Freier Heap",
        icon="mdi:memory",
        native_unit_of_measurement=UnitOfInformation.KILOBYTES,
        device_class=SensorDeviceClass.DATA_SIZE,
        state_class=SensorStateClass.MEASUREMENT,
        value_fn=lambda info: info.get("system", {}).get("freeMem"),
    ),
    GatewaySensorDescription(
        key="api_calls",
        name="API-Aufrufe",
        icon="mdi:api",
        state_class=SensorStateClass.TOTAL_INCREASING,
        value_fn=lambda info: info.get("api", {}).get("APICalls"),
    ),
    GatewaySensorDescription(
        key="api_fails",
        name="API-Fehler",
        icon="mdi:api-off",
        state_class=SensorStateClass.TOTAL_INCREASING,
        value_fn=lambda info: info.get("api", {}).get("APIFails"),
    ),
    GatewaySensorDescription(
        key="bus_telegrams_received",
        name="Empfangene Bus-Telegramme",
        icon="mdi:swap-horizontal",
        state_class=SensorStateClass.TOTAL_INCREASING,
        value_fn=lambda info: info.get("bus", {}).get("busTelegramsReceived"),
    ),
    GatewaySensorDescription(
        key="bus_protocol",
        name="Bus-Protokoll",
        icon="mdi:chip",
        value_fn=lambda info: info.get("bus", {}).get("busProtocol"),
    ),
    GatewaySensorDescription(
        key="bus_rx_quality",
        name="Bus RX-Qualität",
        icon="mdi:signal",
        native_unit_of_measurement=PERCENTAGE,
        state_class=SensorStateClass.MEASUREMENT,
        value_fn=lambda info: info.get("bus", {}).get("busRxLineQuality"),
    ),
    GatewaySensorDescription(
        key="bus_tx_quality",
        name="Bus TX-Qualität",
        icon="mdi:signal",
        native_unit_of_measurement=PERCENTAGE,
        state_class=SensorStateClass.MEASUREMENT,
        value_fn=lambda info: info.get("bus", {}).get("busTxLineQuality"),
    ),
    GatewaySensorDescription(
        key="bus_reads",
        name="Bus Reads",
        icon="mdi:database-import",
        state_class=SensorStateClass.TOTAL_INCREASING,
        value_fn=lambda info: info.get("bus", {}).get("busReads"),
    ),
    GatewaySensorDescription(
        key="bus_reads_failed",
        name="Bus Reads fehlgeschlagen",
        icon="mdi:database-alert",
        state_class=SensorStateClass.TOTAL_INCREASING,
        value_fn=lambda info: info.get("bus", {}).get("busReadsFailed"),
    ),
    GatewaySensorDescription(
        key="bus_writes",
        name="Bus Writes",
        icon="mdi:database-export",
        state_class=SensorStateClass.TOTAL_INCREASING,
        value_fn=lambda info: info.get("bus", {}).get("busWrites"),
    ),
    GatewaySensorDescription(
        key="bus_writes_failed",
        name="Bus Writes fehlgeschlagen",
        icon="mdi:database-alert",
        state_class=SensorStateClass.TOTAL_INCREASING,
        value_fn=lambda info: info.get("bus", {}).get("busWritesFailed"),
    ),
    GatewaySensorDescription(
        key="bus_incomplete_telegrams",
        name="Unvollständige Bus-Telegramme",
        icon="mdi:alert-circle-outline",
        state_class=SensorStateClass.TOTAL_INCREASING,
        value_fn=lambda info: info.get("bus", {}).get("busIncompleteTelegrams"),
    ),
    GatewaySensorDescription(
        key="temperature_sensors_connected",
        name="Angeschlossene Temperatursensoren",
        icon="mdi:thermometer",
        state_class=SensorStateClass.MEASUREMENT,
        value_fn=lambda info: info.get("sensor", {}).get("temperatureSensors"),
    ),
    GatewaySensorDescription(
        key="temperature_sensor_reads",
        name="Temperatursensor-Abfragen",
        icon="mdi:thermometer-lines",
        state_class=SensorStateClass.TOTAL_INCREASING,
        value_fn=lambda info: info.get("sensor", {}).get("temperatureSensorReads"),
    ),
    GatewaySensorDescription(
        key="temperature_sensor_fails",
        name="Temperatursensor-Fehler",
        icon="mdi:thermometer-off",
        state_class=SensorStateClass.TOTAL_INCREASING,
        value_fn=lambda info: info.get("sensor", {}).get("temperatureSensorFails"),
    ),
    GatewaySensorDescription(
        key="analog_sensors_connected",
        name="Angeschlossene Analogsensoren",
        icon="mdi:sine-wave",
        state_class=SensorStateClass.MEASUREMENT,
        value_fn=lambda info: info.get("analog", {}).get("analogSensors"),
    ),
    GatewaySensorDescription(
        key="analog_sensor_reads",
        name="Analogsensor-Abfragen",
        icon="mdi:chart-line",
        state_class=SensorStateClass.TOTAL_INCREASING,
        value_fn=lambda info: info.get("analog", {}).get("analogSensorReads"),
    ),
    GatewaySensorDescription(
        key="analog_sensor_fails",
        name="Analogsensor-Fehler",
        icon="mdi:chart-line-variant",
        state_class=SensorStateClass.TOTAL_INCREASING,
        value_fn=lambda info: info.get("analog", {}).get("analogSensorFails"),
    ),
    GatewaySensorDescription(
        key="reset_reason",
        name="Letzter Neustart-Grund",
        icon="mdi:restart-alert",
        value_fn=lambda info: info.get("system", {}).get("resetReason"),
    ),
    GatewaySensorDescription(
        key="network_type",
        name="Netzwerktyp",
        icon="mdi:lan",
        value_fn=lambda info: info.get("network", {}).get("network"),
    ),
    GatewaySensorDescription(
        key="wifi_rssi",
        name="WLAN-Signalstärke",
        icon="mdi:wifi",
        native_unit_of_measurement="dBm",
        device_class=SensorDeviceClass.SIGNAL_STRENGTH,
        state_class=SensorStateClass.MEASUREMENT,
        # Nur relevant/vorhanden bei WiFi-Betrieb - bei Ethernet (wie aktuell
        # bei Christoph) liefert die API dieses Feld nicht, die Entity wird
        # dann gar nicht erst angelegt (siehe condition_fn in sensor.py).
        condition_fn=lambda info: info.get("network", {}).get("network") == "WiFi"
        and "RSSI" in info.get("network", {}),
        value_fn=lambda info: info.get("network", {}).get("RSSI"),
    ),
    GatewaySensorDescription(
        key="ap_provision_mode",
        name="AP-Fallback-Status",
        icon="mdi:access-point",
        # Rohwert, unveraendert - die genauen moeglichen Zustaende von
        # provisionMode (z.B. ob "disconnected" wirklich der einzige
        # "normale" Wert ist) sind nicht zweifelsfrei dokumentiert/
        # verifiziert. Deshalb bewusst Text statt einer geratenen
        # problem/connectivity-Interpretation.
        value_fn=lambda info: info.get("ap", {}).get("provisionMode"),
    ),
    GatewaySensorDescription(
        key="boot_time",
        name="Letzter Boot",
        icon="mdi:restart",
        device_class=SensorDeviceClass.TIMESTAMP,
        entity_category=None,
        # Kommt ausschliesslich vom MQTT "info"-Topic (einmalig beim Boot
        # gesendet) - REST liefert nur die relative uptimeSec, keinen
        # absoluten Zeitstempel. Erscheint deshalb erst, sobald MQTT
        # mindestens einmal seit dem letzten Neustart verbunden war.
        value_fn=lambda info: dt_util.parse_datetime(info.get("system", {}).get("bootTime"))
        if info.get("system", {}).get("bootTime")
        else None,
    ),
    GatewaySensorDescription(
        key="mqtt_messages_sent",
        name="MQTT-Nachrichten gesendet",
        icon="mdi:upload-network",
        state_class=SensorStateClass.TOTAL_INCREASING,
        # Ebenfalls nur vom MQTT "heartbeat"-Topic - kein REST-Gegenstueck.
        value_fn=lambda info: info.get("mqtt", {}).get("messagesSent"),
    ),
    GatewaySensorDescription(
        key="mqtt_message_fails",
        name="MQTT-Nachrichten fehlgeschlagen",
        icon="mdi:upload-network-outline",
        state_class=SensorStateClass.TOTAL_INCREASING,
        value_fn=lambda info: info.get("mqtt", {}).get("messageFails"),
    ),
    GatewaySensorDescription(
        key="shower_duration",
        name="Duschdauer",
        icon="mdi:shower",
        native_unit_of_measurement=UnitOfTime.SECONDS,
        device_class=SensorDeviceClass.DURATION,
        state_class=SensorStateClass.MEASUREMENT,
        entity_category=None,
        # Nur MQTT (siehe mqtt.py "shower_data"-Topic) - kein REST-
        # Aequivalent, bleibt ohne MQTT dauerhaft "Unbekannt".
        value_fn=lambda info: info.get("shower", {}).get("duration"),
    ),
    GatewaySensorDescription(
        key="shower_min_duration",
        name="Mindestdauer Duscherkennung",
        icon="mdi:shower-head",
        native_unit_of_measurement=UnitOfTime.SECONDS,
        device_class=SensorDeviceClass.DURATION,
        # Konfigurationswert, read-only ueber die API - bereits Teil der
        # regulaeren /api/system/info Sammel-Antwort.
        value_fn=lambda info: info.get("settings", {}).get("showerMinDuration"),
    ),
    GatewaySensorDescription(
        key="shower_alert_trigger",
        name="Duschalarm-Schwelle",
        icon="mdi:alarm-light-outline",
        native_unit_of_measurement=UnitOfTime.MINUTES,
        device_class=SensorDeviceClass.DURATION,
        # Bestaetigt in Minuten (nicht Sekunden!) - siehe EMS-ESP-Doku:
        # "After 7 minutes (configurable) running the hot water it will
        # send out a warning". Nicht Teil der Sammel-Antwort, wird per
        # Einzelabfrage nachgeladen (siehe coordinator.py _EXTRA_SETTINGS).
        value_fn=lambda info: info.get("settings", {}).get("showerAlertTrigger"),
    ),
    GatewaySensorDescription(
        key="shower_alert_coldshot",
        name="Kaltwasserstoß-Dauer",
        icon="mdi:snowflake",
        native_unit_of_measurement=UnitOfTime.SECONDS,
        device_class=SensorDeviceClass.DURATION,
        # Bestaetigt in Sekunden - siehe EMS-ESP-Doku: "sending cold water
        # for 10 seconds (also configurable)". Ebenfalls per Einzelabfrage
        # nachgeladen, nicht Teil der Sammel-Antwort.
        value_fn=lambda info: info.get("settings", {}).get("showerAlertColdshot"),
    ),
)

GATEWAY_BINARY_SENSORS: tuple[GatewayBinarySensorDescription, ...] = (
    GatewayBinarySensorDescription(
        key="bus_connected",
        name="Bus verbunden",
        device_class=BinarySensorDeviceClass.CONNECTIVITY,
        entity_category=None,
        value_fn=lambda info: info.get("bus", {}).get("busStatus") == "connected",
    ),
    GatewayBinarySensorDescription(
        key="mqtt_connected",
        name="MQTT verbunden",
        device_class=BinarySensorDeviceClass.CONNECTIVITY,
        entity_category=None,
        value_fn=lambda info: info.get("mqtt", {}).get("MQTTStatus") == "connected",
    ),
    GatewayBinarySensorDescription(
        key="ntp_connected",
        name="NTP verbunden",
        device_class=BinarySensorDeviceClass.CONNECTIVITY,
        value_fn=lambda info: info.get("ntp", {}).get("NTPstatus") == "connected",
    ),
    GatewayBinarySensorDescription(
        key="modbus_enabled",
        name="Modbus aktiviert",
        icon="mdi:swap-horizontal-bold",
        device_class=BinarySensorDeviceClass.RUNNING,
        value_fn=lambda info: info.get("modbus", {}).get("enabled"),
    ),
    GatewayBinarySensorDescription(
        key="analog_enabled",
        name="Analogsensoren aktiviert",
        icon="mdi:sine-wave",
        device_class=BinarySensorDeviceClass.RUNNING,
        value_fn=lambda info: info.get("analog", {}).get("enabled"),
    ),
    GatewayBinarySensorDescription(
        key="syslog_enabled",
        name="Syslog aktiviert",
        icon="mdi:file-document-outline",
        device_class=BinarySensorDeviceClass.RUNNING,
        value_fn=lambda info: info.get("syslog", {}).get("enabled"),
    ),
    GatewayBinarySensorDescription(
        key="shower_active",
        name="Dusche aktiv",
        icon="mdi:shower",
        device_class=BinarySensorDeviceClass.RUNNING,
        entity_category=None,
        # Nur MQTT (siehe mqtt.py "shower_active"-Topic) - kein REST-
        # Aequivalent, bleibt ohne MQTT dauerhaft "Unbekannt".
        value_fn=lambda info: info.get("shower", {}).get("active"),
    ),
)
