"""Button entities for EMS-ESP integration — dynamically created from API."""
from __future__ import annotations
import logging
from homeassistant.components.button import ButtonEntity
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.helpers.update_coordinator import CoordinatorEntity

from .const import DOMAIN, DEVICE_BOILER
from .coordinator import EmsEspCoordinator
from .entity_factory import classify_entities

_LOGGER = logging.getLogger(__name__)

# Static fallback: (key, name, icon, command_topic, payload)
STATIC_BUTTONS = [
    ("mandefrost", "Abtauen starten", "mdi:snowflake-melt", "boiler/mandefrost", "on"),
]


async def async_setup_entry(
    hass: HomeAssistant,
    entry: ConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    coordinator: EmsEspCoordinator = hass.data[DOMAIN][entry.entry_id]
    entities: list = []

    api_entities: dict = entry.data.get("api_entities", {})

    if api_entities:
        classified = classify_entities(api_entities)
        for meta in classified.get("button", []):
            entities.append(EmsEspDynamicButton(coordinator, meta))
        _LOGGER.info("EMS-ESP: %d dynamic buttons created", len(classified.get("button", [])))
    else:
        for key, name, icon, cmd, payload in STATIC_BUTTONS:
            entities.append(EmsEspStaticButton(coordinator, key, name, icon, cmd, payload))

    async_add_entities(entities)


class _EmsEspButtonBase(CoordinatorEntity, ButtonEntity):
    _attr_has_entity_name = True

    def __init__(self, coordinator: EmsEspCoordinator):
        super().__init__(coordinator)

    @property
    def device_info(self): return self.coordinator.boiler_device_info

    @property
    def available(self) -> bool: return self.coordinator.gateway_info.online


class EmsEspDynamicButton(_EmsEspButtonBase):
    def __init__(self, coordinator: EmsEspCoordinator, meta: dict):
        super().__init__(coordinator)
        self._meta = meta
        self._key  = meta["name"]
        self._device_type = meta.get("device_type", "boiler")
        self._cmd_topic = f"{self._device_type}/{self._key}"
        self._attr_unique_id = f"{coordinator.entry_id}_{self._device_type}_{self._key}"
        self._attr_name = meta.get("fullname") or self._key

    async def async_press(self) -> None:
        await self.coordinator.async_publish_command(self._cmd_topic, "on")

    @property
    def extra_state_attributes(self) -> dict:
        return {"ems_esp_key": self._key, "device_type": self._device_type}


class EmsEspStaticButton(_EmsEspButtonBase):
    def __init__(self, coordinator, key, name, icon, cmd_topic, payload):
        super().__init__(coordinator)
        self._key       = key
        self._cmd_topic = cmd_topic
        self._payload   = payload
        self._attr_unique_id = f"{coordinator.entry_id}_{key}"
        self._attr_name = name
        self._attr_icon = icon

    async def async_press(self) -> None:
        await self.coordinator.async_publish_command(self._cmd_topic, self._payload)

    @property
    def extra_state_attributes(self) -> dict:
        return {"ems_esp_key": self._key}
