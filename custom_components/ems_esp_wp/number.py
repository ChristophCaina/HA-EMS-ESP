"""Number entities for EMS-ESP integration — dynamically created from API."""
from __future__ import annotations
import logging
from homeassistant.components.number import NumberEntity, NumberMode
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.helpers.update_coordinator import CoordinatorEntity

from .const import DOMAIN, DEVICE_BOILER, DEVICE_DHW
from .coordinator import EmsEspCoordinator
from .entity_factory import classify_entities

_LOGGER = logging.getLogger(__name__)

# Static fallback definitions: (key, name, min, max, step, unit, device_type, command_topic)
STATIC_NUMBERS = [
    ("wwseltemp",          "WW Solltemperatur",         35,   65,  1,   "°C", DEVICE_DHW,    "boiler/wwseltemp"),
    ("flowtempmax",        "HC1 VL Maximum",            30,   85,  1,   "°C", "hc1",         "thermostat/hc1/flowtempmax"),
    ("flowtempmin",        "HC1 VL Minimum",            10,   40,  1,   "°C", "hc1",         "thermostat/hc1/flowtempmin"),
    ("heatslope",          "HC1 Heizkurve Neigung",    0.1,  4.0, 0.1,  "",  "hc1",         "thermostat/hc1/heatslope"),
    ("hpmaxpower",         "Max. Kompressorleistung",   0,   100,  1,   "%", DEVICE_BOILER,  "boiler/hpmaxpower"),
    ("designtemp",         "HC1 Normaußentemperatur",  -25,   0,   1,  "°C", "hc1",         "thermostat/hc1/designtemp"),
    ("remotetemp",         "HC1 Fernfühler Raumtemp.", -20,   30,  0.5,"°C", "hc1",         "thermostat/hc1/remotetemp"),
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
        for meta in classified.get("number", []):
            entities.append(EmsEspDynamicNumber(coordinator, meta))
        _LOGGER.info("EMS-ESP: %d dynamic numbers created", len(classified.get("number", [])))
    else:
        for key, name, mn, mx, step, unit, device_type, cmd in STATIC_NUMBERS:
            entities.append(EmsEspStaticNumber(
                coordinator, key, name, mn, mx, step, unit, device_type, cmd
            ))

    async_add_entities(entities)


class _EmsEspNumberBase(CoordinatorEntity, NumberEntity):
    _attr_has_entity_name = True
    _attr_mode = NumberMode.BOX

    def __init__(self, coordinator: EmsEspCoordinator):
        super().__init__(coordinator)

    @property
    def available(self) -> bool:
        return self.coordinator.gateway_info.online

    async def _publish(self, topic: str, value: float) -> None:
        await self.coordinator.async_publish_command(topic, str(value))


class EmsEspDynamicNumber(_EmsEspNumberBase):
    def __init__(self, coordinator: EmsEspCoordinator, meta: dict):
        super().__init__(coordinator)
        self._meta = meta
        self._key  = meta["name"]
        self._device_type = meta.get("device_type", "boiler")
        self._cmd_topic = f"{self._device_type}/{self._key}"
        self._attr_unique_id = f"{coordinator.entry_id}_{self._device_type}_{self._key}"
        self._attr_name = meta.get("fullname") or self._key
        self._attr_native_unit_of_measurement = meta.get("unit")
        self._attr_device_class  = meta.get("device_class")
        self._attr_native_min_value = meta.get("number_min", 0)
        self._attr_native_max_value = meta.get("number_max", 9999)
        self._attr_native_step      = meta.get("number_step", 1)
        if meta.get("entity_category"):
            self._attr_entity_category = meta["entity_category"]

    @property
    def device_info(self):
        dt = self._device_type
        if dt == "thermostat": return self.coordinator.hc_device_info(1)
        if dt == "dhw":        return self.coordinator.dhw_device_info
        return self.coordinator.boiler_device_info

    @property
    def native_value(self) -> float | None:
        if not self.coordinator.data: return None
        d = self.coordinator.data
        if self._device_type == "boiler" and d.get("boiler"):
            return d["boiler"].raw.get(self._key)
        if self._device_type == "thermostat" and d.get("thermostat"):
            return d["thermostat"].raw.get(self._key)
        return None

    async def async_set_native_value(self, value: float) -> None:
        await self._publish(self._cmd_topic, value)

    @property
    def extra_state_attributes(self) -> dict:
        return {"ems_esp_key": self._key, "device_type": self._device_type}


class EmsEspStaticNumber(_EmsEspNumberBase):
    def __init__(self, coordinator, key, name, mn, mx, step, unit, device_type, cmd_topic):
        super().__init__(coordinator)
        self._key = key
        self._device_type = device_type
        self._cmd_topic   = cmd_topic
        self._attr_unique_id = f"{coordinator.entry_id}_{key}"
        self._attr_name = name
        self._attr_native_unit_of_measurement = unit or None
        self._attr_native_min_value = mn
        self._attr_native_max_value = mx
        self._attr_native_step      = step

    @property
    def device_info(self):
        if self._device_type == DEVICE_DHW: return self.coordinator.dhw_device_info
        if self._device_type == "hc1":      return self.coordinator.hc_device_info(1)
        return self.coordinator.boiler_device_info

    @property
    def native_value(self) -> float | None:
        if not self.coordinator.data: return None
        d = self.coordinator.data
        if self._device_type == DEVICE_DHW and d.get("dhw"):
            return d["dhw"].raw.get(self._key) or getattr(d["dhw"], self._key, None)
        if self._device_type == "hc1" and d.get("thermostat"):
            hc = d["thermostat"].hcs.get(1)
            return hc.raw.get(self._key) if hc else None
        if d.get("boiler"):
            return d["boiler"].raw.get(self._key)
        return None

    async def async_set_native_value(self, value: float) -> None:
        await self._publish(self._cmd_topic, value)

    @property
    def extra_state_attributes(self) -> dict:
        return {"ems_esp_key": self._key}
