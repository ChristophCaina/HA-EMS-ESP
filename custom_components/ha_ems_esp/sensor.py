"""Sensor-Plattform fuer ha_ems_esp.

Zwei Quellen:
- Statische Gateway-Diagnose-Sensoren (siehe gateway_diagnostics.py)
- Dynamische, read-only Sensoren aus /api/<device>/entities (alles was
  entity_factory nicht als number/switch/binary_sensor einordnet, also
  read-only "number"-Typen und - vorerst - auch "enum"-Typen, siehe
  entity_factory.py Docstring zum Enum/Select-TODO)
"""
from __future__ import annotations

from typing import Any

from homeassistant.components.sensor import SensorDeviceClass, SensorEntity
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity import DeviceInfo
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.helpers.update_coordinator import CoordinatorEntity

from .const import CONF_HOST, DOMAIN
from .coordinator import EmsEspSystemCoordinator
from .dynamic_entity import EmsDynamicEntity, async_setup_dynamic_platform
from .entity_factory import EmsEntityPlatform
from .gateway_diagnostics import GATEWAY_SENSORS, GatewaySensorDescription


async def async_setup_entry(
    hass: HomeAssistant, entry: ConfigEntry, async_add_entities: AddEntitiesCallback
) -> None:
    data = hass.data[DOMAIN][entry.entry_id]
    system_coordinator: EmsEspSystemCoordinator = data["system_coordinator"]

    async_add_entities(
        GatewayDiagnosticSensor(system_coordinator, entry, description)
        for description in GATEWAY_SENSORS
        if description.condition_fn(system_coordinator.merged_data())
    )
    async_add_entities([ConfiguredHostSensor(entry)])

    async_setup_dynamic_platform(
        hass, entry, async_add_entities, EmsEntityPlatform.SENSOR, EmsDynamicSensor
    )


class GatewayDiagnosticSensor(CoordinatorEntity[EmsEspSystemCoordinator], SensorEntity):
    """Ein einzelner Diagnose-Wert aus /api/system/info."""

    _attr_has_entity_name = True

    def __init__(
        self,
        coordinator: EmsEspSystemCoordinator,
        entry: ConfigEntry,
        description: GatewaySensorDescription,
    ) -> None:
        super().__init__(coordinator)
        self._description = description
        self._attr_unique_id = f"{entry.unique_id or entry.entry_id}_{description.key}"
        self._attr_name = description.name
        self._attr_icon = description.icon
        self._attr_native_unit_of_measurement = description.native_unit_of_measurement
        self._attr_device_class = description.device_class
        self._attr_state_class = description.state_class
        self._attr_entity_category = description.entity_category
        self._attr_device_info = DeviceInfo(
            identifiers={(DOMAIN, entry.unique_id or entry.entry_id)}
        )

    @property
    def native_value(self):
        merged = self.coordinator.merged_data()
        if not merged:
            return None
        return self._description.value_fn(merged)


class EmsDynamicSensor(EmsDynamicEntity, SensorEntity):
    """Read-only Sensor aus /api/<device>/entities (number-read-only oder enum)."""

    def __init__(self, coordinator, entry, descriptor) -> None:
        super().__init__(coordinator, entry, descriptor)
        self._attr_native_unit_of_measurement = descriptor.unit
        if descriptor.device_class_hint:
            try:
                self._attr_device_class = SensorDeviceClass(descriptor.device_class_hint)
            except ValueError:
                pass

    @property
    def native_value(self) -> Any:
        raw = self._current_raw()
        return raw.get("value") if raw else None


class ConfiguredHostSensor(SensorEntity):
    """Spiegelt die im Config Flow eingetragene Host-Adresse.

    KEIN geraeteseitig gemeldeter Wert - EMS-ESP liefert die tatsaechliche
    IP ueber /api/system/info nicht (offener Community-Wunsch, siehe
    emsesp/EMS-ESP32#202). Das hier ist schlicht das, was wir selbst
    anwaehlen, aber wenigstens im Dashboard sichtbar statt nur in den
    Integrations-Einstellungen.
    """

    _attr_has_entity_name = True
    _attr_icon = "mdi:ip-network"
    _attr_entity_category = None

    def __init__(self, entry: ConfigEntry) -> None:
        self._attr_unique_id = f"{entry.unique_id or entry.entry_id}_configured_host"
        self._attr_name = "Konfigurierte Adresse"
        self._attr_native_value = entry.data[CONF_HOST]
        self._attr_device_info = DeviceInfo(
            identifiers={(DOMAIN, entry.unique_id or entry.entry_id)}
        )
