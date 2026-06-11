"""Binary sensor entities for EMS-ESP integration — dynamically created from API."""
from __future__ import annotations
import logging
from homeassistant.components.binary_sensor import BinarySensorDeviceClass, BinarySensorEntity
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.helpers.update_coordinator import CoordinatorEntity

from .const import DOMAIN, DEVICE_BOILER, DEVICE_DHW
from .coordinator import EmsEspCoordinator
from .entity_factory import classify_entities

_LOGGER = logging.getLogger(__name__)

# Static fallback: (key, name, device_class, device_type)
STATIC_BINARY_SENSORS = [
    ("heatingactive",  "Heizung aktiv",    BinarySensorDeviceClass.RUNNING, DEVICE_BOILER),
    ("tapwateractive", "Warmwasser aktiv", BinarySensorDeviceClass.RUNNING, DEVICE_DHW),
    ("hpcompon",       "Kompressor aktiv", BinarySensorDeviceClass.RUNNING, DEVICE_BOILER),
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
        for meta in classified.get("binary_sensor", []):
            entities.append(EmsEspDynamicBinarySensor(coordinator, meta))
        _LOGGER.info("EMS-ESP: %d dynamic binary sensors created", len(classified.get("binary_sensor", [])))
    else:
        for key, name, dc, device_type in STATIC_BINARY_SENSORS:
            entities.append(EmsEspStaticBinarySensor(coordinator, key, name, dc, device_type))

    async_add_entities(entities)


class _EmsEspBinarySensorBase(CoordinatorEntity, BinarySensorEntity):
    _attr_has_entity_name = True

    def __init__(self, coordinator: EmsEspCoordinator):
        super().__init__(coordinator)

    @property
    def available(self) -> bool:
        return self.coordinator.gateway_info.online

    def _parse_bool(self, val) -> bool | None:
        if val is None: return None
        if isinstance(val, bool): return val
        return str(val).lower() in ("on", "true", "1", "yes", "heating", "hot water")


class EmsEspDynamicBinarySensor(_EmsEspBinarySensorBase):
    def __init__(self, coordinator: EmsEspCoordinator, meta: dict):
        super().__init__(coordinator)
        self._meta = meta
        self._key  = meta["name"]
        self._device_type = meta.get("device_type", "boiler")
        self._attr_unique_id = f"{coordinator.entry_id}_{self._device_type}_{self._key}"
        self._attr_name = meta.get("fullname") or self._key
        self._attr_device_class = meta.get("device_class")
        if meta.get("entity_category"):
            self._attr_entity_category = meta["entity_category"]

    @property
    def device_info(self):
        if self._device_type == "dhw": return self.coordinator.dhw_device_info
        return self.coordinator.boiler_device_info

    @property
    def is_on(self) -> bool | None:
        if not self.coordinator.data: return None
        d = self.coordinator.data
        val = None
        if self._device_type == "boiler" and d.get("boiler"):
            val = d["boiler"].raw.get(self._key)
        elif self._device_type == "thermostat" and d.get("thermostat"):
            val = d["thermostat"].raw.get(self._key)
        return self._parse_bool(val)

    @property
    def extra_state_attributes(self) -> dict:
        return {"ems_esp_key": self._key, "device_type": self._device_type}


class EmsEspStaticBinarySensor(_EmsEspBinarySensorBase):
    def __init__(self, coordinator, key, name, dc, device_type):
        super().__init__(coordinator)
        self._key = key
        self._device_type = device_type
        self._attr_unique_id = f"{coordinator.entry_id}_{key}"
        self._attr_name = name
        self._attr_device_class = dc

    @property
    def device_info(self):
        if self._device_type == DEVICE_DHW: return self.coordinator.dhw_device_info
        return self.coordinator.boiler_device_info

    @property
    def is_on(self) -> bool | None:
        if not self.coordinator.data: return None
        d = self.coordinator.data
        if self._device_type == DEVICE_DHW and d.get("dhw"):
            return self._parse_bool(d["dhw"].raw.get(self._key))
        if d.get("boiler"):
            val = d["boiler"].raw.get(self._key)
            # heating_active and tapwater_active come as "on"/"off" strings
            return self._parse_bool(val)
        return None

    @property
    def extra_state_attributes(self) -> dict:
        return {"ems_esp_key": self._key}
