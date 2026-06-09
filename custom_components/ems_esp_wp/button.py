"""Button entities for EMS-ESP (one-shot commands)."""
from __future__ import annotations
from homeassistant.components.button import ButtonEntity
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.helpers.update_coordinator import CoordinatorEntity

from .const import DOMAIN, DEVICE_BOILER
from .coordinator import EmsEspCoordinator


async def async_setup_entry(
    hass: HomeAssistant,
    entry: ConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    coordinator: EmsEspCoordinator = hass.data[DOMAIN][entry.entry_id]
    async_add_entities([
        EmsEspButton(coordinator, "mandefrost", "Manuelles Abtauen",
            icon="mdi:snowflake-melt",
            command_topic="boiler/mandefrost", command_payload="on"),
    ])


class EmsEspButton(CoordinatorEntity, ButtonEntity):
    def __init__(self, coordinator, key, name, icon, command_topic, command_payload):
        super().__init__(coordinator)
        self._command_topic = command_topic
        self._command_payload = command_payload
        self._attr_unique_id = f"{coordinator.entry_id}_{key}"
        self._attr_name = name
        self._attr_icon = icon
        self._attr_has_entity_name = True

    @property
    def device_info(self):
        return self.coordinator.boiler_device_info

    async def async_press(self) -> None:
        await self.coordinator.async_publish_command(self._command_topic, self._command_payload)

    @property
    def available(self) -> bool:
        return self.coordinator.gateway_info.online
