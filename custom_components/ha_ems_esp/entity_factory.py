"""Generische Ableitung von HA-Entity-Beschreibungen aus /api/<device>/entities.

Bestaetigt gegen echte Payloads (analogsensor/temperaturesensor):
- Die API liefert ein Objekt {kurzname: {details}}, keine Liste - api.py
  normalisiert das bereits zu einer Liste von Detail-Dicts.
- "fullname" ist bei is_system-Entities identisch zum technischen "name"
  (keine echte Uebersetzung). Bei echten EMS-Bus-Geraeten (Boiler,
  Thermostat) soll fullname laut EMS-ESP-Community lesbaren, je nach
  Geraete-Locale uebersetzten Text liefern - das ist mit echten Daten aber
  noch nicht verifiziert. Fuer den Fall "fullname == name" gibt es einen
  einfachen Praettify-Fallback.

WICHTIGER TODO: enum-Typ (z.B. pvmode) wird aktuell NICHT als select
abgebildet. Die /entities Antwort liefert nur den aktuellen Wert, keine
Liste gueltiger Optionen - SelectEntity braucht aber eine vollstaendige
Optionsliste. Bis wir eine echte Enum-Entity-Antwort von einem
angeschlossenen EMS-Geraet gesehen haben (ggf. liefert der Einzel-Endpunkt
/api/<device>/<entity> mehr Metadaten), fallen enum-Entities auf einen
read-only Sensor zurueck, der den aktuellen String-Wert zeigt.
"""
from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum
from typing import Any

from homeassistant.config_entries import ConfigEntry
from homeassistant.const import EntityCategory
from homeassistant.helpers.entity import DeviceInfo

from .const import DOMAIN, GATEWAY_LOCAL_DEVICE_TYPES

EMS_TYPE_NUMBER = "number"
EMS_TYPE_BOOLEAN = "boolean"
EMS_TYPE_ENUM = "enum"


class EmsEntityPlatform(StrEnum):
    SENSOR = "sensor"
    NUMBER = "number"
    SWITCH = "switch"
    BINARY_SENSOR = "binary_sensor"
    # SELECT folgt, sobald Enum-Optionen aus der API bekannt sind (siehe TODO oben)


# Deutsche Anzeigenamen fuer bekannte EMS-Geraetetypen (= HA Device-Name).
# Faellt auf eine simple Titel-Schreibweise des rohen Typs zurueck, wenn
# ein Typ hier (noch) nicht gelistet ist.
DEVICE_TYPE_DISPLAY_NAMES: dict[str, str] = {
    "boiler": "Boiler / Wärmepumpe",
    "heatpump": "Wärmepumpe",
    "thermostat": "Thermostat",
    "mixer": "Mischer",
    "solar": "Solarmodul",
    "switch": "Schaltmodul",
    "controller": "Controller",
    "pump": "Pumpe",
    "heatsource": "Wärmequelle",
    "ventilation": "Lüftung",
    "generic": "Custom Entities",
    "temperaturesensor": "Temperatursensor",
    "analogsensor": "Analogsensor",
}


# Manuelle Ausnahmen fuer einzelne (device_type, key)-Paare - fuer Faelle,
# in denen die generische Ableitung (is_system -> diagnostic, fullname/
# prettify -> Anzeigename) nicht das gewuenschte Ergebnis liefert.
DISPLAY_NAME_OVERRIDES: dict[tuple[str, str], str] = {
    ("analogsensor", "led"): "Status-LED",
}

# is_system-Entities, die TROTZDEM nicht als Diagnose gelten sollen, weil
# sie "auf einen Blick sehen ob alles laeuft"-Werte sind statt reiner
# Technik-Zahlen (Absprache mit Christoph).
PROMOTED_FROM_DIAGNOSTIC: set[tuple[str, str]] = {
    ("temperaturesensor", "gateway_temperature"),
    ("analogsensor", "led"),
    ("analogsensor", "supply_voltage"),
}


# Ordnet bekannte API-Einheiten (uom) einer HA device_class zu, als reiner
# String-Wert (kompatibel sowohl mit sensor.SensorDeviceClass als auch
# number.NumberDeviceClass, die beide dieselben String-Werte nutzen - die
# jeweilige Plattform castet selbst in ihre eigene Enum). Gilt generisch
# fuer ALLE Entities, nicht nur die aktuell bekannten - kommt spaeter z.B.
# Boiler/Waermepumpe-Sollwerten (°C, bar) automatisch zugute.
UOM_DEVICE_CLASS_MAP: dict[str, str] = {
    "°C": "temperature",
    "°F": "temperature",
    "V": "voltage",
    "A": "current",
    "W": "power",
    "kW": "power",
    "Wh": "energy",
    "kWh": "energy",
    "Hz": "frequency",
    "bar": "pressure",
    "mbar": "pressure",
    "Pa": "pressure",
}


@dataclass(frozen=True, kw_only=True)
class EmsEntityDescriptor:
    """Von der API abgeleitete, HA-taugliche Beschreibung einer Entity."""

    device_type: str
    key: str  # kurzer technischer Name, z.B. "core_voltage"
    display_name: str
    platform: EmsEntityPlatform
    unit: str | None
    writeable: bool
    entity_category: EntityCategory | None
    min_value: float | None
    max_value: float | None
    numeric_bool: bool  # True: type=="number" aber semantisch 0/1-binaer (siehe _is_binary_number)
    device_class_hint: str | None  # siehe UOM_DEVICE_CLASS_MAP, String statt konkreter Enum
    raw: dict[str, Any]

    @property
    def unique_id_suffix(self) -> str:
        return f"{self.device_type}_{self.key}"


def _prettify(key: str) -> str:
    """Fallback-Anzeigename, wenn fullname == name (keine echte Uebersetzung)."""
    return key.replace("_", " ").strip().capitalize()


def _is_binary_number(entity: dict[str, Any]) -> bool:
    """True fuer type=="number"-Entities, die eigentlich 0/1-binaer sind.

    Beispiel: das "led"-Feld aus /api/analogsensor/entities kommt mit
    type=="number", min=0, max=1 - technisch eine Zahl, semantisch ein
    Ein/Aus-Schalter. Statt eines Zahlen-Sliders (0-1) bauen wir daraus
    einen echten switch/binary_sensor.
    """
    if entity.get("type") != EMS_TYPE_NUMBER:
        return False
    return entity.get("min") == 0 and entity.get("max") == 1


def _platform_for(entity: dict[str, Any]) -> EmsEntityPlatform:
    ems_type = entity.get("type")
    writeable = bool(entity.get("writeable"))

    if ems_type == EMS_TYPE_BOOLEAN or _is_binary_number(entity):
        return EmsEntityPlatform.SWITCH if writeable else EmsEntityPlatform.BINARY_SENSOR
    if ems_type == EMS_TYPE_NUMBER:
        return EmsEntityPlatform.NUMBER if writeable else EmsEntityPlatform.SENSOR
    # enum (noch kein select, siehe Modul-Docstring) und alles Unbekannte
    # (z.B. "text"): als Sensor darstellen.
    return EmsEntityPlatform.SENSOR


def build_entity_descriptor(device_type: str, entity: dict[str, Any]) -> EmsEntityDescriptor:
    key = entity.get("name", "")
    fullname = entity.get("fullname") or key
    override_name = DISPLAY_NAME_OVERRIDES.get((device_type, key))
    display_name = override_name or (fullname if fullname != key else _prettify(key))

    is_diagnostic = bool(entity.get("is_system")) and (device_type, key) not in PROMOTED_FROM_DIAGNOSTIC
    unit = entity.get("uom") or None

    return EmsEntityDescriptor(
        device_type=device_type,
        key=key,
        display_name=display_name,
        platform=_platform_for(entity),
        unit=unit,
        writeable=bool(entity.get("writeable")),
        entity_category=EntityCategory.DIAGNOSTIC if is_diagnostic else None,
        min_value=entity.get("min"),
        max_value=entity.get("max"),
        numeric_bool=_is_binary_number(entity),
        device_class_hint=UOM_DEVICE_CLASS_MAP.get(unit) if unit else None,
        raw=entity,
    )


def build_entity_descriptors(
    device_type: str, entities: list[dict[str, Any]]
) -> list[EmsEntityDescriptor]:
    """Baut Descriptors fuer alle sichtbaren, benannten Entities eines Geraetetyps."""
    return [
        build_entity_descriptor(device_type, entity)
        for entity in entities
        if entity.get("visible", True) and entity.get("name")
    ]


def is_gateway_local(device_type: str) -> bool:
    """True, wenn die Entities dieses Typs am Gateway-Device haengen sollen."""
    return device_type in GATEWAY_LOCAL_DEVICE_TYPES


def device_display_name(device_type: str) -> str:
    return DEVICE_TYPE_DISPLAY_NAMES.get(device_type, device_type.replace("_", " ").title())


def device_info_for(device_type: str, entry: ConfigEntry) -> DeviceInfo:
    """Loest die HA-Device-Zuordnung fuer einen EMS-ESP Geraetetyp auf.

    Gateway-lokale Typen (siehe GATEWAY_LOCAL_DEVICE_TYPES) haengen direkt
    am Gateway-Device (gleiche identifiers) - echte EMS-Bus-Geraete
    bekommen ein eigenes Device mit via_device zum Gateway.
    """
    gateway_id = entry.unique_id or entry.entry_id
    gateway_identifier = (DOMAIN, gateway_id)

    if is_gateway_local(device_type):
        return DeviceInfo(identifiers={gateway_identifier})

    return DeviceInfo(
        identifiers={(DOMAIN, f"{gateway_id}_{device_type}")},
        via_device=gateway_identifier,
        name=device_display_name(device_type),
        manufacturer="EMS-ESP",
    )


_TRUTHY_STRINGS = {"on", "an", "ein", "true", "1", "yes", "ja"}
_FALSY_STRINGS = {"off", "aus", "false", "0", "no", "nein"}


def coerce_bool(value: Any) -> bool | None:
    """Interpretiert einen rohen EMS-ESP boolean-Wert.

    EMS-ESP kann je nach settings.boolFormat (siehe /api/system/info)
    unterschiedliche Darstellungen liefern (0/1, true/false, on/off, oder
    lokalisiert an/aus) - deshalb robust auf mehrere bekannte Formen
    pruefen statt nur bool()/int() zu erwarten. None, wenn der Wert nicht
    eindeutig interpretierbar ist.
    """
    if isinstance(value, bool):
        return value
    if isinstance(value, (int, float)):
        return bool(value)
    if isinstance(value, str):
        normalized = value.strip().lower()
        if normalized in _TRUTHY_STRINGS:
            return True
        if normalized in _FALSY_STRINGS:
            return False
    return None
