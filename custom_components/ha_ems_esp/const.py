"""Constants for the ha_ems_esp integration.

Architektur (Neustart, siehe Konzept-Absprache):
- Gateway wird immer als eigenes HA-Device angelegt (Basis: /api/system/info).
- Jedes am Bus erkannte EMS-Geraet (boiler, heatpump, thermostat, ...) wird als
  eigenes HA-Device angelegt, per via_device an das Gateway gehaengt.
- Struktur-Discovery laeuft primaer ueber REST (/api/<device>/entities), mit
  MQTT-Discovery-Payloads als Fallback, falls REST zur Laufzeit nicht erreichbar ist.
- Live-Werte kommen ueber MQTT (Gesamttopic/JSON), nicht ueber REST-Polling.
- Schreibpfad ist konfigurierbar: REST-POST, MQTT-Publish oder beides.
"""
from __future__ import annotations

DOMAIN = "ha_ems_esp"

# ---------------------------------------------------------------------------
# Config Flow / Options Flow keys
# ---------------------------------------------------------------------------
CONF_HOST = "host"
CONF_API_TOKEN = "api_token"
CONF_MQTT_BASE_TOPIC = "mqtt_base_topic"
CONF_MQTT_DISCOVERY_ENABLED = "mqtt_discovery_enabled"
CONF_MQTT_DISCOVERY_PREFIX = "mqtt_discovery_prefix"
CONF_WRITE_MODE = "write_mode"
CONF_STRUCTURE_SCAN_INTERVAL = "structure_scan_interval"

# ---------------------------------------------------------------------------
# Defaults
# ---------------------------------------------------------------------------
DEFAULT_MQTT_BASE_TOPIC = "ems-esp"
DEFAULT_MQTT_DISCOVERY_ENABLED = True
DEFAULT_MQTT_DISCOVERY_PREFIX = "homeassistant"
DEFAULT_STRUCTURE_SCAN_INTERVAL = 300  # Sekunden, Poll auf /entities je bekanntem Device-Typ
DEFAULT_SYSTEM_INFO_SCAN_INTERVAL = 60  # Sekunden, Poll auf /api/system/info (Diagnose)

# ---------------------------------------------------------------------------
# Schreibpfad-Optionen fuer Kommandos (number.set_value, select.select_option, ...)
# ---------------------------------------------------------------------------
WRITE_MODE_REST = "rest"
WRITE_MODE_MQTT = "mqtt"
WRITE_MODE_BOTH = "both"
WRITE_MODE_DEFAULT = WRITE_MODE_BOTH
WRITE_MODES = [WRITE_MODE_REST, WRITE_MODE_MQTT, WRITE_MODE_BOTH]

# ---------------------------------------------------------------------------
# Nur "Home Assistant" Discovery-Format wird von uns geparst.
# EMS-ESP kennt zusaetzlich "Domoticz" / "Domoticz (latest)" - anderes Payload-
# Format, wird von uns ignoriert (kein Fallback verfuegbar, aber kein Fehler).
# ---------------------------------------------------------------------------
SUPPORTED_MQTT_DISCOVERY_TYPE = "homeassistant"

# ---------------------------------------------------------------------------
# REST API Pfade (siehe https://emsesp.org/Commands)
# ---------------------------------------------------------------------------
API_PATH_SYSTEM_INFO = "/api/system/info"
API_PATH_DEVICE_ENTITIES = "/api/{device}/entities"
API_PATH_DEVICE_COMMAND = "/api/{device}/{command}"

# ---------------------------------------------------------------------------
# Firmware-Versionscheck (reine Information, siehe update.py - KEIN
# automatisches Flashen, Risiko eines Bricks bei falscher Binary-Variante).
# ---------------------------------------------------------------------------
GITHUB_LATEST_RELEASE_URL = "https://api.github.com/repos/emsesp/EMS-ESP32/releases/latest"
DEFAULT_FIRMWARE_CHECK_INTERVAL = 43200  # 12 Stunden in Sekunden

# Referenz-Liste bekannter EMS-ESP Geraetetypen (aus der emsesp.org Commands-
# Referenz). Wird NICHT mehr fuer den Struktur-Poll verwendet - die
# Coordinators lesen die tatsaechlich vorhandenen Geraete direkt aus
# /api/system/info -> "devices". Bleibt als Nachschlagehilfe fuer spaeter
# (z.B. Icons/Uebersetzung pro Geraetetyp in entity_factory.py).
KNOWN_EMS_DEVICE_TYPES = [
    "boiler",
    "thermostat",
    "mixer",
    "solar",
    "heatpump",
    "switch",
    "controller",
    "pump",
    "heatsource",
    "ventilation",
    "generic",
]

# Platzhalter-Device-Typ fuer das Gateway selbst (kein EMS-Bus-Geraet).
GATEWAY_DEVICE_TYPE = "gateway"

# ---------------------------------------------------------------------------
# Geraetetypen aus /api/system/info -> "devices", die KEINE eigenstaendigen
# EMS-Bus-Geraete sind, sondern physisch am EMS-ESP-Board selbst haengen
# (Dallas 1-Wire Temperatursensoren, analoge GPIO-Eingaenge). Deren Entities
# werden dem Gateway-Device selbst zugeordnet (gleiche device identifiers),
# NICHT als eigenes via_device-Geraet angelegt - im Gegensatz zu echten
# EMS-Bus-Geraeten wie boiler/thermostat/heatpump/mixer/....
#
# entity_factory.py muss diese Unterscheidung bei der Device-Zuordnung
# beachten: device_type in GATEWAY_LOCAL_DEVICE_TYPES -> Entity haengt am
# Gateway-Device; sonst -> eigenes Device mit via_device=Gateway.
# ---------------------------------------------------------------------------
GATEWAY_LOCAL_DEVICE_TYPES = {"temperaturesensor", "analogsensor"}
