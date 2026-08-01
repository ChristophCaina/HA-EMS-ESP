"""Binary-Sensor-Plattform fuer ha_ems_esp.

Zwei Quellen: statische Gateway-Diagnose-Zustaende (siehe
gateway_diagnostics.py) und dynamische read-only boolean Entities aus
/api/<device>/entities.
"""
from __future__ import annotations

from homeassistant.components.binary_sensor import BinarySensorEntity
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity import DeviceInfo
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.helpers.update_coordinator import CoordinatorEntity

from .const import DOMAIN
from .coordinator import EmsEspSystemCoordinator
from .dynamic_entity import EmsDynamicEntity, async_setup_dynamic_platform
from .entity_factory import EmsEntityPlatform, coerce_bool
from .gateway_diagnostics import GATEWAY_BINARY_SENSORS, GatewayBinarySensorDescription


async def async_setup_entry(
    hass: HomeAssistant, entry: ConfigEntry, async_add_entities: AddEntitiesCallback
) -> None:
    data = hass.data[DOMAIN][entry.entry_id]
    system_coordinator: EmsEspSystemCoordinator = data["system_coordinator"]

    async_add_entities(
        GatewayDiagnosticBinarySensor(system_coordinator, entry, description)
        for description in GATEWAY_BINARY_SENSORS
    )

    async_setup_dynamic_platform(
        hass,
        entry,
        async_add_entities,
        EmsEntityPlatform.BINARY_SENSOR,
        EmsDynamicBinarySensor,
    )


class GatewayDiagnosticBinarySensor(
    CoordinatorEntity[EmsEspSystemCoordinator], BinarySensorEntity
):
    """Ein einzelner boolescher Diagnose-Zustand aus /api/system/info."""

    _attr_has_entity_name = True

    def __init__(
        self,
        coordinator: EmsEspSystemCoordinator,
        entry: ConfigEntry,
        description: GatewayBinarySensorDescription,
    ) -> None:
        super().__init__(coordinator)
        self._description = description
        self._attr_unique_id = f"{entry.unique_id or entry.entry_id}_{description.key}"
        self._attr_name = description.name
        self._attr_icon = description.icon
        self._attr_device_class = description.device_class
        self._attr_entity_category = description.entity_category
        self._attr_device_info = DeviceInfo(
            identifiers={(DOMAIN, entry.unique_id or entry.entry_id)}
        )

    @property
    def is_on(self) -> bool | None:
        merged = self.coordinator.merged_data()
        if not merged:
            return None
        return self._description.value_fn(merged)


class EmsDynamicBinarySensor(EmsDynamicEntity, BinarySensorEntity):
    """Read-only boolean Sensor aus /api/<device>/entities."""

    @property
    def is_on(self) -> bool | None:
        raw = self._current_raw()
        if raw is None:
            return None
        return coerce_bool(raw.get("value"))
