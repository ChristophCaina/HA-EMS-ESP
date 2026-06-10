"""
EMS-ESP Entity Factory — creates HA entities dynamically from API entity list.

Each entity returned by GET /api/<device>/entities has:
  name:      entity key (e.g. "pvmode", "hpcurrpower")
  fullname:  human readable name
  type:      "boolean" | "int" | "float" | "enum" | "string" | "cmd"
  writeable: true/false
  uom:       unit of measurement ("°C", "W", "kWh", "%", "")
  value:     current value

From this we create the appropriate HA entity type:
  boolean + writeable  → switch
  boolean + read-only  → binary_sensor
  int/float + writeable → number
  int/float + read-only → sensor
  enum + writeable     → select
  enum + read-only     → sensor
  string               → sensor
  cmd                  → button
"""
from __future__ import annotations
import logging
from typing import Any

from homeassistant.components.sensor import SensorDeviceClass, SensorStateClass
from homeassistant.components.binary_sensor import BinarySensorDeviceClass
from homeassistant.components.number import NumberMode
from homeassistant.const import (
    EntityCategory,
    UnitOfEnergy,
    UnitOfPower,
    UnitOfTemperature,
    UnitOfTime,
    PERCENTAGE,
)

_LOGGER = logging.getLogger(__name__)

# Unit of measurement string → HA unit constant
UOM_MAP: dict[str, str] = {
    "°C":    UnitOfTemperature.CELSIUS,
    "W":     UnitOfPower.WATT,
    "kW":    UnitOfPower.KILO_WATT,
    "kWh":   UnitOfEnergy.KILO_WATT_HOUR,
    "%":     PERCENTAGE,
    "min":   UnitOfTime.MINUTES,
    "h":     UnitOfTime.HOURS,
    "s":     UnitOfTime.SECONDS,
    "bar":   "bar",
    "l/min": "L/min",
    "rpm":   "rpm",
}

# Entity name patterns → device_class hints
SENSOR_DEVICE_CLASS_MAP: dict[str, SensorDeviceClass] = {
    "temp":     SensorDeviceClass.TEMPERATURE,
    "power":    SensorDeviceClass.POWER,
    "nrg":      SensorDeviceClass.ENERGY,
    "meter":    SensorDeviceClass.ENERGY,
    "energy":   SensorDeviceClass.ENERGY,
    "uptime":   SensorDeviceClass.DURATION,
    "duration": SensorDeviceClass.DURATION,
}

BINARY_DEVICE_CLASS_MAP: dict[str, BinarySensorDeviceClass] = {
    "active":   BinarySensorDeviceClass.RUNNING,
    "on":       BinarySensorDeviceClass.RUNNING,
    "compon":   BinarySensorDeviceClass.RUNNING,
    "pump":     BinarySensorDeviceClass.RUNNING,
}

# Entities that should be DIAGNOSTIC (not shown in main view)
DIAGNOSTIC_PATTERNS = {
    "hptc", "hptr", "hptl", "hppl", "hpph",  # refrigerant temps
    "burnstarts", "burnworkmin", "uptime",      # statistics
    "servicecode", "servicecodenumber",
    "nrgconstotal", "nrgcons",                  # legacy counters
    "version", "busstatus", "freemem",
}

# Entities that are TOTAL_INCREASING (energy counters)
TOTAL_INCREASING_PATTERNS = {
    "nrgtotal", "nrgheat", "nrgcool", "nrg",
    "metertotal", "metercomp", "metereheat", "meterheat", "metercool", "meter",
    "nrgsupptotal", "nrgsuppheating", "nrgsupp",
    "nrgconstotal", "nrgconscomptotal", "nrgconscompheating",
    "auxelecheatnrgconstotal", "burnstarts", "burnworkmin",
    "uptimetotal", "uptimecontrol",
}


def _ha_uom(uom: str) -> str | None:
    """Convert EMS-ESP unit string to HA unit constant."""
    return UOM_MAP.get(uom.strip()) if uom else None


def _is_diagnostic(name: str) -> bool:
    return any(p in name.lower() for p in DIAGNOSTIC_PATTERNS)


def _is_total_increasing(name: str) -> bool:
    return name.lower() in TOTAL_INCREASING_PATTERNS


def _sensor_device_class(name: str, uom: str) -> SensorDeviceClass | None:
    n = name.lower()
    for pattern, dc in SENSOR_DEVICE_CLASS_MAP.items():
        if pattern in n:
            return dc
    # Also check by unit
    if uom in ("°C",):
        return SensorDeviceClass.TEMPERATURE
    if uom in ("W", "kW"):
        return SensorDeviceClass.POWER
    if uom in ("kWh",):
        return SensorDeviceClass.ENERGY
    return None


def _binary_device_class(name: str) -> BinarySensorDeviceClass | None:
    n = name.lower()
    for pattern, dc in BINARY_DEVICE_CLASS_MAP.items():
        if pattern in n:
            return dc
    return None


def classify_entity(entity: dict) -> dict:
    """
    Classify an EMS-ESP entity dict into HA entity metadata.

    Returns a dict with:
      ha_type:       "sensor" | "binary_sensor" | "number" | "select" |
                     "switch" | "button" | "climate" | None
      unit:          HA unit string or None
      device_class:  HA device_class or None
      state_class:   HA state_class or None
      entity_category: EntityCategory.DIAGNOSTIC or None
      options:       list of enum values (for select/sensor)
      number_min:    min value for number
      number_max:    max value for number
      number_step:   step for number
      icon:          mdi icon suggestion
    """
    name      = entity.get("name", "")
    fullname  = entity.get("fullname", name)
    etype     = entity.get("type", "string")
    writeable = entity.get("writeable", False)
    uom       = entity.get("uom", "")
    options   = entity.get("options", [])  # for enum types

    result: dict[str, Any] = {
        "ha_type":        None,
        "unit":           _ha_uom(uom),
        "device_class":   None,
        "state_class":    None,
        "entity_category": EntityCategory.DIAGNOSTIC if _is_diagnostic(name) else None,
        "options":        options,
        "number_min":     None,
        "number_max":     None,
        "number_step":    1,
        "icon":           None,
        "name":           name,
        "fullname":       fullname,
        "writeable":      writeable,
        "uom":            uom,
        "etype":          etype,
    }

    # ── type = cmd → button ────────────────────────────────────────────────
    if etype == "cmd":
        result["ha_type"] = "button"
        return result

    # ── type = boolean ────────────────────────────────────────────────────
    if etype == "boolean":
        if writeable:
            result["ha_type"] = "switch"
        else:
            result["ha_type"] = "binary_sensor"
            result["device_class"] = _binary_device_class(name)
        return result

    # ── type = enum ───────────────────────────────────────────────────────
    if etype == "enum":
        if writeable:
            result["ha_type"] = "select"
        else:
            result["ha_type"] = "sensor"
        return result

    # ── type = int / float ────────────────────────────────────────────────
    if etype in ("int", "float"):
        dc = _sensor_device_class(name, uom)
        sc = None

        if _is_total_increasing(name):
            sc = SensorStateClass.TOTAL_INCREASING
        elif dc in (SensorDeviceClass.TEMPERATURE, SensorDeviceClass.POWER):
            sc = SensorStateClass.MEASUREMENT

        if writeable:
            result["ha_type"] = "number"
            result["device_class"] = dc
            # Set sensible defaults for number ranges based on unit
            if uom == "°C":
                result["number_min"]  = -30
                result["number_max"]  = 90
                result["number_step"] = 0.5 if etype == "float" else 1
            elif uom == "%":
                result["number_min"]  = 0
                result["number_max"]  = 100
                result["number_step"] = 1
            elif uom in ("W", "kW"):
                result["number_min"]  = 0
                result["number_max"]  = 20000
                result["number_step"] = 10
            else:
                result["number_min"]  = 0
                result["number_max"]  = 9999
                result["number_step"] = 1 if etype == "int" else 0.1
        else:
            result["ha_type"]    = "sensor"
            result["device_class"] = dc
            result["state_class"]  = sc
        return result

    # ── type = string ─────────────────────────────────────────────────────
    result["ha_type"] = "sensor"
    return result


def classify_entities(api_entities: dict) -> dict[str, list[dict]]:
    """
    Classify all entities from all device types.
    
    Input:  {"boiler": [...], "thermostat": [...], ...}
    Output: {"sensor": [...], "binary_sensor": [...], "number": [...], ...}
    """
    classified: dict[str, list[dict]] = {
        "sensor": [], "binary_sensor": [], "number": [],
        "select": [], "switch": [], "button": [],
    }

    for device_type, entity_list in api_entities.items():
        if not isinstance(entity_list, list):
            continue
        for entity in entity_list:
            meta = classify_entity(entity)
            meta["device_type"] = device_type  # boiler / thermostat / etc.
            ha_type = meta.get("ha_type")
            if ha_type and ha_type in classified:
                classified[ha_type].append(meta)
            elif ha_type:
                classified[ha_type] = [meta]

    total = sum(len(v) for v in classified.values())
    _LOGGER.info(
        "EMS-ESP entity factory: %d entities classified (%s)",
        total,
        ", ".join(f"{k}={len(v)}" for k, v in classified.items() if v)
    )
    return classified
