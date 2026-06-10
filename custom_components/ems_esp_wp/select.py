"""Select entities for EMS-ESP integration — dynamically created from API."""
from __future__ import annotations
import logging
from homeassistant.components.select import SelectEntity
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.helpers.update_coordinator import CoordinatorEntity

from .const import DOMAIN, DEVICE_BOILER
from .coordinator import EmsEspCoordinator
from .entity_factory import classify_entities

_LOGGER = logging.getLogger(__name__)

# Static fallback: (key, name, options, device_type, command_topic)
STATIC_SELECTS = [
    ("pvmode",    "PV Modus",       ["off","low","medium","high"],    DEVICE_BOILER, "boiler/pvmode"),
    ("silentmode","Silent Modus",   ["0","1","2","3"],                DEVICE_BOILER, "boiler/silentmode"),
    ("wwcomfort", "WW Komfort",     ["hot","eco","intelligent"],      DEVICE_BOILER, "boiler/wwcomfort"),
    ("mode",      "HC1 Betriebsart",["auto","day","night","eco","nofrost"], "hc1",  "thermostat/hc1/mode"),
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
        for meta in classified.get("select", []):
            entities.append(EmsEspDynamicSelect(coordinator, meta))
        _LOGGER.info("EMS-ESP: %d dynamic selects created", len(classified.get("select", [])))
    else:
        for key, name, options, device_type, cmd in STATIC_SELECTS:
            entities.append(EmsEspStaticSelect(coordinator, key, name, options, device_type, cmd))

    async_add_entities(entities)


class _EmsEspSelectBase(CoordinatorEntity, SelectEntity):
    _attr_has_entity_name = True

    def __init__(self, coordinator: EmsEspCoordinator):
        super().__init__(coordinator)

    @property
    def available(self) -> bool:
        return self.coordinator.gateway_info.online


class EmsEspDynamicSelect(_EmsEspSelectBase):
    def __init__(self, coordinator: EmsEspCoordinator, meta: dict):
        super().__init__(coordinator)
        self._meta = meta
        self._key  = meta["name"]
        self._device_type = meta.get("device_type", "boiler")
        self._cmd_topic = f"{self._device_type}/{self._key}"
        self._attr_unique_id = f"{coordinator.entry_id}_{self._device_type}_{self._key}"
        self._attr_name = meta.get("fullname") or self._key
        self._attr_options = [str(o) for o in meta.get("options", [])]
        if meta.get("entity_category"):
            self._attr_entity_category = meta["entity_category"]

    @property
    def device_info(self):
        dt = self._device_type
        if dt == "thermostat": return self.coordinator.hc_device_info(1)
        return self.coordinator.boiler_device_info

    @property
    def current_option(self) -> str | None:
        if not self.coordinator.data: return None
        d = self.coordinator.data
        if self._device_type == "boiler" and d.get("boiler"):
            return d["boiler"].raw.get(self._key)
        if self._device_type == "thermostat" and d.get("thermostat"):
            return d["thermostat"].raw.get(self._key)
        return None

    async def async_select_option(self, option: str) -> None:
        await self.coordinator.async_publish_command(self._cmd_topic, option)

    @property
    def extra_state_attributes(self) -> dict:
        return {"ems_esp_key": self._key, "device_type": self._device_type}


class EmsEspStaticSelect(_EmsEspSelectBase):
    def __init__(self, coordinator, key, name, options, device_type, cmd_topic):
        super().__init__(coordinator)
        self._key = key
        self._device_type = device_type
        self._cmd_topic   = cmd_topic
        self._attr_unique_id = f"{coordinator.entry_id}_{key}"
        self._attr_name    = name
        self._attr_options = options

    @property
    def device_info(self):
        if self._device_type == "hc1": return self.coordinator.hc_device_info(1)
        return self.coordinator.boiler_device_info

    @property
    def current_option(self) -> str | None:
        if not self.coordinator.data: return None
        d = self.coordinator.data
        if self._device_type == "hc1" and d.get("thermostat"):
            hc = d["thermostat"].hcs.get(1)
            return hc.raw.get(self._key) if hc else None
        if d.get("boiler"):
            return d["boiler"].raw.get(self._key)
        return None

    async def async_select_option(self, option: str) -> None:
        await self.coordinator.async_publish_command(self._cmd_topic, option)

    @property
    def extra_state_attributes(self) -> dict:
        return {"ems_esp_key": self._key}
