"""Sensor entities for EMS-ESP integration — dynamically created from API."""
from __future__ import annotations
import logging
from typing import Any

from homeassistant.components.sensor import (
    SensorDeviceClass, SensorEntity, SensorStateClass,
)
from homeassistant.config_entries import ConfigEntry
from homeassistant.const import EntityCategory, UnitOfEnergy, UnitOfPower, UnitOfTemperature
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.helpers.update_coordinator import CoordinatorEntity

from .const import DOMAIN, DEVICE_GATEWAY, DEVICE_BOILER, DEVICE_DHW, DEVICE_HC
from .coordinator import EmsEspCoordinator
from .entity_factory import classify_entities

_LOGGER = logging.getLogger(__name__)


async def async_setup_entry(
    hass: HomeAssistant,
    entry: ConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    coordinator: EmsEspCoordinator = hass.data[DOMAIN][entry.entry_id]
    entities: list = []

    # ── Gateway sensors (always static) ───────────────────────────────────
    for key, name, icon in [
        ("gateway_version",    "Version",    "mdi:chip"),
        ("gateway_uptime",     "Uptime",     "mdi:timer-outline"),
        ("gateway_bus_status", "Bus Status", "mdi:lan-connect"),
    ]:
        entities.append(EmsEspGatewaySensor(coordinator, key, name, icon))

    # ── Dynamic entities from API or fallback static list ─────────────────
    api_entities: dict = entry.data.get("api_entities", {})

    if api_entities:
        classified = classify_entities(api_entities)
        for meta in classified.get("sensor", []):
            entities.append(EmsEspDynamicSensor(coordinator, meta))
        _LOGGER.info("EMS-ESP: %d dynamic sensors created", len(classified.get("sensor", [])))
    else:
        # Fallback: static sensor list when no IP/API available
        _LOGGER.info("EMS-ESP: no API entities — using static fallback sensors")
        for key, name, unit, dc, sc, device_type, diag in STATIC_SENSORS:
            entities.append(EmsEspStaticSensor(
                coordinator, key, name, unit, dc, sc, device_type, diag
            ))

    # ── Calculated sensors (always added — COP, SPF) ──────────────────────
    entities.append(EmsEspCopSensor(coordinator))
    entities.append(EmsEspSpfSensor(coordinator))

    async_add_entities(entities)


# ── Static fallback list (used when no EMS-ESP IP configured) ─────────────
STATIC_SENSORS = [
    # key, name, unit, device_class, state_class, device_type, diagnostic
    ("curflowtemp",  "Vorlauftemperatur",        UnitOfTemperature.CELSIUS, SensorDeviceClass.TEMPERATURE, SensorStateClass.MEASUREMENT,     DEVICE_BOILER, False),
    ("rettemp",      "Rücklauftemperatur",        UnitOfTemperature.CELSIUS, SensorDeviceClass.TEMPERATURE, SensorStateClass.MEASUREMENT,     DEVICE_BOILER, False),
    ("outdoortemp",  "Außentemperatur",           UnitOfTemperature.CELSIUS, SensorDeviceClass.TEMPERATURE, SensorStateClass.MEASUREMENT,     DEVICE_BOILER, False),
    ("selflowtemp",  "Vorlauf Solltemperatur",    UnitOfTemperature.CELSIUS, SensorDeviceClass.TEMPERATURE, SensorStateClass.MEASUREMENT,     DEVICE_BOILER, False),
    ("hpcurrpower",  "Leistungsaufnahme (elektrisch)", UnitOfPower.WATT,    SensorDeviceClass.POWER,        SensorStateClass.MEASUREMENT,     DEVICE_BOILER, False),
    ("hppower",      "Thermische Leistung",       UnitOfPower.KILO_WATT,    SensorDeviceClass.POWER,        SensorStateClass.MEASUREMENT,     DEVICE_BOILER, False),
    ("nrgtotal",     "Wärme gesamt",              UnitOfEnergy.KILO_WATT_HOUR, SensorDeviceClass.ENERGY,   SensorStateClass.TOTAL_INCREASING, DEVICE_BOILER, False),
    ("nrgheat",      "Wärme Heizen",              UnitOfEnergy.KILO_WATT_HOUR, SensorDeviceClass.ENERGY,   SensorStateClass.TOTAL_INCREASING, DEVICE_BOILER, False),
    ("metertotal",   "Strom gesamt",              UnitOfEnergy.KILO_WATT_HOUR, SensorDeviceClass.ENERGY,   SensorStateClass.TOTAL_INCREASING, DEVICE_BOILER, False),
    ("metercomp",    "Strom Kompressor",          UnitOfEnergy.KILO_WATT_HOUR, SensorDeviceClass.ENERGY,   SensorStateClass.TOTAL_INCREASING, DEVICE_BOILER, False),
    ("metereheat",   "Strom E-Heizer",            UnitOfEnergy.KILO_WATT_HOUR, SensorDeviceClass.ENERGY,   SensorStateClass.TOTAL_INCREASING, DEVICE_BOILER, False),
    ("meterheat",    "Strom Heizen",              UnitOfEnergy.KILO_WATT_HOUR, SensorDeviceClass.ENERGY,   SensorStateClass.TOTAL_INCREASING, DEVICE_BOILER, False),
    ("servicecode",  "Servicecode",               None, None, None, DEVICE_BOILER, True),
    ("hpactivity",   "WP Aktivität",              None, None, None, DEVICE_BOILER, False),
    # DHW — keys match raw dict keys from parser/simulator
    ("curtemp",      "Warmwasser Ist-Temperatur", UnitOfTemperature.CELSIUS, SensorDeviceClass.TEMPERATURE, SensorStateClass.MEASUREMENT,     DEVICE_DHW, False),
    ("curtemp2",     "Warmwasser ext. Temperatur",UnitOfTemperature.CELSIUS, SensorDeviceClass.TEMPERATURE, SensorStateClass.MEASUREMENT,     DEVICE_DHW, False),
    ("settemp",      "Warmwasser Stop-Temperatur",UnitOfTemperature.CELSIUS, SensorDeviceClass.TEMPERATURE, SensorStateClass.MEASUREMENT,     DEVICE_DHW, False),
    ("nrg",          "WWK Wärme gesamt",          UnitOfEnergy.KILO_WATT_HOUR, SensorDeviceClass.ENERGY,   SensorStateClass.TOTAL_INCREASING, DEVICE_DHW, False),
    ("meter",        "WWK Strom gesamt",           UnitOfEnergy.KILO_WATT_HOUR, SensorDeviceClass.ENERGY,   SensorStateClass.TOTAL_INCREASING, DEVICE_DHW, False),
]


class _EmsEspSensorBase(CoordinatorEntity, SensorEntity):
    """Base class for all EMS-ESP sensors."""
    _attr_has_entity_name = True

    def __init__(self, coordinator: EmsEspCoordinator):
        super().__init__(coordinator)

    @property
    def available(self) -> bool:
        return self.coordinator.gateway_info.online

    def _raw(self, key: str, device_type: str = "boiler") -> Any:
        """Get raw value from coordinator data by key and device_type."""
        if not self.coordinator.data:
            return None
        d = self.coordinator.data
        if device_type == "boiler" and d.get("boiler"):
            return getattr(d["boiler"], key, None) or d["boiler"].raw.get(key)
        if device_type == "thermostat" and d.get("thermostat"):
            return d["thermostat"].raw.get(key)
        if device_type in ("dhw",) and d.get("dhw"):
            return getattr(d["dhw"], key, None) or d["dhw"].raw.get(key)
        return None


class EmsEspGatewaySensor(_EmsEspSensorBase):
    """Static gateway sensor."""

    def __init__(self, coordinator, key, name, icon):
        super().__init__(coordinator)
        self._key = key
        self._attr_unique_id = f"{coordinator.entry_id}_{key}"
        self._attr_name = name
        self._attr_icon = icon
        self._attr_entity_category = EntityCategory.DIAGNOSTIC
        if key == "gateway_uptime":
            from homeassistant.const import UnitOfTime
            self._attr_native_unit_of_measurement = UnitOfTime.SECONDS
            self._attr_device_class = SensorDeviceClass.DURATION
            self._attr_state_class  = SensorStateClass.MEASUREMENT

    @property
    def device_info(self):
        return self.coordinator.gateway_device_info

    @property
    def native_value(self):
        gw = self.coordinator.gateway_info
        if self._key == "gateway_version":    return gw.version
        if self._key == "gateway_uptime":     return gw.uptime_seconds
        if self._key == "gateway_bus_status": return gw.bus_status
        return None


class EmsEspDynamicSensor(_EmsEspSensorBase):
    """Sensor created dynamically from EMS-ESP API entity list."""

    def __init__(self, coordinator: EmsEspCoordinator, meta: dict):
        super().__init__(coordinator)
        self._meta = meta
        self._key  = meta["name"]
        self._device_type = meta.get("device_type", "boiler")
        self._attr_unique_id = f"{coordinator.entry_id}_{self._device_type}_{self._key}"
        self._attr_name = meta.get("fullname") or self._key
        self._attr_native_unit_of_measurement = meta.get("unit")
        self._attr_device_class  = meta.get("device_class")
        self._attr_state_class   = meta.get("state_class")
        if meta.get("entity_category"):
            self._attr_entity_category = meta["entity_category"]

    @property
    def device_info(self):
        dt = self._device_type
        if dt == "thermostat": return self.coordinator.hc_device_info(1)
        if dt in ("dhw",):     return self.coordinator.dhw_device_info
        return self.coordinator.boiler_device_info

    @property
    def native_value(self):
        return self._raw(self._key, self._device_type)

    @property
    def extra_state_attributes(self) -> dict:
        return {"ems_esp_key": self._key, "device_type": self._device_type}


class EmsEspStaticSensor(_EmsEspSensorBase):
    """Static fallback sensor."""

    def __init__(self, coordinator, key, name, unit, dc, sc, device_type, diagnostic):
        super().__init__(coordinator)
        self._key = key
        self._device_type = device_type
        self._attr_unique_id = f"{coordinator.entry_id}_{key}"
        self._attr_name = name
        self._attr_native_unit_of_measurement = unit
        self._attr_device_class  = dc
        self._attr_state_class   = sc
        if diagnostic:
            self._attr_entity_category = EntityCategory.DIAGNOSTIC

    @property
    def device_info(self):
        if self._device_type == DEVICE_DHW:    return self.coordinator.dhw_device_info
        if self._device_type == DEVICE_GATEWAY: return self.coordinator.gateway_device_info
        return self.coordinator.boiler_device_info

    @property
    def native_value(self):
        if not self.coordinator.data: return None
        d = self.coordinator.data
        if self._device_type == DEVICE_DHW:
            dhw = d.get("dhw")
            if not dhw: return None
            return dhw.raw.get(self._key)
        return self._raw(self._key, self._device_type)

    @property
    def extra_state_attributes(self) -> dict:
        return {"ems_esp_key": self._key}


class EmsEspCopSensor(_EmsEspSensorBase):
    """Calculated COP sensor."""
    _attr_name = "COP aktuell"
    _attr_icon = "mdi:heat-pump"
    _attr_state_class = SensorStateClass.MEASUREMENT

    def __init__(self, coordinator):
        super().__init__(coordinator)
        self._attr_unique_id = f"{coordinator.entry_id}_cop_current"

    @property
    def device_info(self): return self.coordinator.boiler_device_info

    @property
    def native_value(self):
        d = self.coordinator.data
        if not d or not d.get("boiler"): return None
        b = d["boiler"]
        out = b.hp_power_output or b.raw.get("hppower")
        inp = b.hp_power_input  or b.raw.get("hpcurrpower")
        if out is None or inp is None or inp <= 0: return None
        # hppower is kW, hpcurrpower is W
        out_kw = out if out < 100 else out / 1000
        inp_kw = inp / 1000
        return round(out_kw / inp_kw, 2)

    @property
    def extra_state_attributes(self) -> dict:
        return {"calculated": True, "formula": "hppower_kW / hpcurrpower_kW"}


class EmsEspSpfSensor(_EmsEspSensorBase):
    """Calculated Seasonal Performance Factor sensor."""
    _attr_name = "Jahresarbeitszahl (SPF)"
    _attr_icon = "mdi:chart-line"
    _attr_state_class = SensorStateClass.MEASUREMENT

    def __init__(self, coordinator):
        super().__init__(coordinator)
        self._attr_unique_id = f"{coordinator.entry_id}_cop_seasonal"

    @property
    def device_info(self): return self.coordinator.boiler_device_info

    @property
    def native_value(self):
        d = self.coordinator.data
        if not d or not d.get("boiler"): return None
        b = d["boiler"]
        thermal  = b.nrg_total  or b.raw.get("nrgtotal")
        elec     = b.meter_total or b.raw.get("metertotal") or \
                   b.nrg_cons_total or b.raw.get("nrgconstotal")
        if not thermal or not elec or elec <= 0: return None
        spf = thermal / elec
        return round(spf, 2) if 1.0 <= spf <= 8.0 else None

    @property
    def extra_state_attributes(self) -> dict:
        return {"calculated": True, "formula": "nrgtotal / metertotal"}
