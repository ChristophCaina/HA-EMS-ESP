"""Switch entities for EMS-ESP."""
from __future__ import annotations
from homeassistant.components.switch import SwitchEntity
from homeassistant.config_entries import ConfigEntry
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
        EmsEspSwitch(coordinator, "wwactivated", "Warmwasser aktiviert",
            device_type=DEVICE_DHW,
            command_topic="boiler/wwactivated",
            value_fn=lambda d: d["dhw"].activated if d["dhw"] else True),
    ])


class EmsEspSwitch(CoordinatorEntity, SwitchEntity):
    def __init__(self, coordinator, key, name, device_type, command_topic, value_fn):
        super().__init__(coordinator)
        self._key = key
        self._command_topic = command_topic
        self._value_fn = value_fn
        self._device_type = device_type
        self._attr_unique_id = f"{coordinator.entry_id}_{key}"
        self._attr_name = name
        self._attr_has_entity_name = True

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

    async def async_turn_on(self, **kwargs) -> None:
        await self.coordinator.async_publish_command(self._command_topic, "on")

    async def async_turn_off(self, **kwargs) -> None:
        await self.coordinator.async_publish_command(self._command_topic, "off")

    @property
    def available(self) -> bool:
        return self.coordinator.gateway_info.online
