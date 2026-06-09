"""Binary sensor entities for EMS-ESP."""
from __future__ import annotations
from homeassistant.components.binary_sensor import (
    BinarySensorDeviceClass,
    BinarySensorEntity,
)
from homeassistant.config_entries import ConfigEntry
from homeassistant.const import EntityCategory
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.helpers.update_coordinator import CoordinatorEntity

from .const import DOMAIN, DEVICE_BOILER, DEVICE_DHW
from .coordinator import EmsEspCoordinator


async def async_setup_entry(
    hass: HomeAssistant,
    entry: ConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    coordinator: EmsEspCoordinator = hass.data[DOMAIN][entry.entry_id]
    async_add_entities([
        EmsEspBinarySensor(coordinator, "heating_active", "Heizung aktiv",
            BinarySensorDeviceClass.RUNNING, DEVICE_BOILER,
            lambda d: d["boiler"].heating_active if d["boiler"] else False),
        EmsEspBinarySensor(coordinator, "hp_compressor", "Kompressor aktiv",
            BinarySensorDeviceClass.RUNNING, DEVICE_BOILER,
            lambda d: d["boiler"].hp_compressor_on if d["boiler"] else False,
            diagnostic=True),
        EmsEspBinarySensor(coordinator, "dhw_active", "Warmwasser aktiv",
            BinarySensorDeviceClass.RUNNING, DEVICE_DHW,
            lambda d: d["dhw"].active if d["dhw"] else False),
        EmsEspBinarySensor(coordinator, "heatingpump", "Heizungspumpe aktiv",
            BinarySensorDeviceClass.RUNNING, DEVICE_BOILER,
            lambda d: d["boiler"].heating_pump if d["boiler"] else False,
            diagnostic=True),
    ])


class EmsEspBinarySensor(CoordinatorEntity, BinarySensorEntity):
    def __init__(self, coordinator, key, name, device_class, device_type, value_fn, diagnostic=False):
        super().__init__(coordinator)
        self._key = key
        self._value_fn = value_fn
        self._device_type = device_type
        self._attr_unique_id = f"{coordinator.entry_id}_{key}"
        self._attr_name = name
        self._attr_device_class = device_class
        self._attr_has_entity_name = True
        if diagnostic:
            self._attr_entity_category = EntityCategory.DIAGNOSTIC

    @property
    def device_info(self):
        if self._device_type == DEVICE_DHW:
            return self.coordinator.dhw_device_info
        return self.coordinator.boiler_device_info

    @property
    def is_on(self):
        if self.coordinator.data:
            return self._value_fn(self.coordinator.data)
        return False

    @property
    def available(self) -> bool:
        return self.coordinator.gateway_info.online
