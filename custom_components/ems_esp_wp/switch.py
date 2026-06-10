"""Switch entities for EMS-ESP integration — dynamically created from API."""
from __future__ import annotations
import logging
from homeassistant.components.switch import SwitchEntity
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.helpers.update_coordinator import CoordinatorEntity

from .const import DOMAIN, DEVICE_BOILER, DEVICE_DHW
from .coordinator import EmsEspCoordinator
from .entity_factory import classify_entities

_LOGGER = logging.getLogger(__name__)

# Static fallback: (key, name, device_type, command_topic)
STATIC_SWITCHES = [
    ("wwactivated",     "WW aktiviert",     DEVICE_DHW,    "boiler/wwactivated"),
    ("heatingactivated","Heizung aktiviert", DEVICE_BOILER, "boiler/heatingactivated"),
    ("forceheatingoff", "Heizung zwangsaus", DEVICE_BOILER, "boiler/forceheatingoff"),
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
        for meta in classified.get("switch", []):
            entities.append(EmsEspDynamicSwitch(coordinator, meta))
        _LOGGER.info("EMS-ESP: %d dynamic switches created", len(classified.get("switch", [])))
    else:
        for key, name, device_type, cmd in STATIC_SWITCHES:
            entities.append(EmsEspStaticSwitch(coordinator, key, name, device_type, cmd))

    async_add_entities(entities)


class _EmsEspSwitchBase(CoordinatorEntity, SwitchEntity):
    _attr_has_entity_name = True

    def __init__(self, coordinator: EmsEspCoordinator):
        super().__init__(coordinator)

    @property
    def available(self) -> bool:
        return self.coordinator.gateway_info.online


class EmsEspDynamicSwitch(_EmsEspSwitchBase):
    def __init__(self, coordinator: EmsEspCoordinator, meta: dict):
        super().__init__(coordinator)
        self._meta = meta
        self._key  = meta["name"]
        self._device_type = meta.get("device_type", "boiler")
        self._cmd_topic = f"{self._device_type}/{self._key}"
        self._attr_unique_id = f"{coordinator.entry_id}_{self._device_type}_{self._key}"
        self._attr_name = meta.get("fullname") or self._key
        if meta.get("entity_category"):
            self._attr_entity_category = meta["entity_category"]

    @property
    def device_info(self):
        dt = self._device_type
        if dt == "thermostat": return self.coordinator.hc_device_info(1)
        if dt == "dhw":        return self.coordinator.dhw_device_info
        return self.coordinator.boiler_device_info

    def _get_raw(self):
        if not self.coordinator.data: return None
        d = self.coordinator.data
        if self._device_type == "boiler" and d.get("boiler"):
            return d["boiler"].raw.get(self._key)
        if self._device_type == "thermostat" and d.get("thermostat"):
            return d["thermostat"].raw.get(self._key)
        return None

    @property
    def is_on(self) -> bool | None:
        val = self._get_raw()
        if val is None: return None
        if isinstance(val, bool): return val
        return str(val).lower() in ("on", "true", "1", "yes")

    async def async_turn_on(self, **kwargs) -> None:
        await self.coordinator.async_publish_command(self._cmd_topic, "on")

    async def async_turn_off(self, **kwargs) -> None:
        await self.coordinator.async_publish_command(self._cmd_topic, "off")

    @property
    def extra_state_attributes(self) -> dict:
        return {"ems_esp_key": self._key, "device_type": self._device_type}


class EmsEspStaticSwitch(_EmsEspSwitchBase):
    def __init__(self, coordinator, key, name, device_type, cmd_topic):
        super().__init__(coordinator)
        self._key = key
        self._device_type = device_type
        self._cmd_topic   = cmd_topic
        self._attr_unique_id = f"{coordinator.entry_id}_{key}"
        self._attr_name = name

    @property
    def device_info(self):
        if self._device_type == DEVICE_DHW: return self.coordinator.dhw_device_info
        return self.coordinator.boiler_device_info

    @property
    def is_on(self) -> bool | None:
        if not self.coordinator.data: return None
        d = self.coordinator.data
        val = None
        if self._device_type == DEVICE_DHW and d.get("dhw"):
            val = d["dhw"].raw.get(self._key) or getattr(d["dhw"], self._key, None)
        elif d.get("boiler"):
            val = d["boiler"].raw.get(self._key)
        if val is None: return None
        if isinstance(val, bool): return val
        return str(val).lower() in ("on", "true", "1", "yes")

    async def async_turn_on(self, **kwargs) -> None:
        await self.coordinator.async_publish_command(self._cmd_topic, "on")

    async def async_turn_off(self, **kwargs) -> None:
        await self.coordinator.async_publish_command(self._cmd_topic, "off")

    @property
    def extra_state_attributes(self) -> dict:
        return {"ems_esp_key": self._key}
