"""Select entities for EMS-ESP (mode selectors)."""
from __future__ import annotations
from homeassistant.components.select import SelectEntity
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.helpers.update_coordinator import CoordinatorEntity

from .const import DOMAIN, DEVICE_BOILER, DEVICE_HC
from .coordinator import EmsEspCoordinator


async def async_setup_entry(
    hass: HomeAssistant,
    entry: ConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    coordinator: EmsEspCoordinator = hass.data[DOMAIN][entry.entry_id]
    async_add_entities([
        EmsEspSelect(coordinator, "pvmode", "PV-Modus",
            options=["off", "low", "medium", "high"],
            device_type=DEVICE_BOILER,
            command_topic="boiler/pvmode",
            value_fn=lambda d: d["boiler"].pv_mode if d["boiler"] and d["boiler"].pv_mode else "off"),
        EmsEspSelect(coordinator, "silentmode", "Silent-Modus",
            options=["0", "1", "2", "3"],
            device_type=DEVICE_BOILER,
            command_topic="boiler/silentmode",
            value_fn=lambda d: str(d["boiler"].silent_mode) if d["boiler"] and d["boiler"].silent_mode is not None else "0"),
        EmsEspSelect(coordinator, "hc1_mode", "HC1 Betriebsart",
            options=["auto", "day", "night", "eco", "nofrost"],
            device_type=DEVICE_HC,
            command_topic="thermostat/hc1/mode",
            value_fn=lambda d: d["thermostat"].hcs[1].mode if d["thermostat"] and 1 in d["thermostat"].hcs and d["thermostat"].hcs[1].mode else "auto"),
    ])


class EmsEspSelect(CoordinatorEntity, SelectEntity):
    def __init__(self, coordinator, key, name, options, device_type, command_topic, value_fn):
        super().__init__(coordinator)
        self._key = key
        self._command_topic = command_topic
        self._value_fn = value_fn
        self._device_type = device_type
        self._attr_unique_id = f"{coordinator.entry_id}_{key}"
        self._attr_name = name
        self._attr_options = options
        self._attr_has_entity_name = True

    @property
    def device_info(self):
        if self._device_type == DEVICE_HC:
            return self.coordinator.hc_device_info(1)
        return self.coordinator.boiler_device_info

    @property
    def current_option(self):
        if self.coordinator.data:
            return self._value_fn(self.coordinator.data)
        return None

    async def async_select_option(self, option: str) -> None:
        await self.coordinator.async_publish_command(self._command_topic, option)

    @property
    def available(self) -> bool:
        return self.coordinator.gateway_info.online
