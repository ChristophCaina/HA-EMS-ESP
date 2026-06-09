"""Number entities for EMS-ESP (writable setpoints)."""
from __future__ import annotations
from homeassistant.components.number import NumberEntity, NumberMode
from homeassistant.config_entries import ConfigEntry
from homeassistant.const import UnitOfTemperature
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.helpers.update_coordinator import CoordinatorEntity

from .const import DOMAIN, DEVICE_BOILER, DEVICE_DHW, DEVICE_HC
from .coordinator import EmsEspCoordinator


async def async_setup_entry(
    hass: HomeAssistant,
    entry: ConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    coordinator: EmsEspCoordinator = hass.data[DOMAIN][entry.entry_id]
    async_add_entities([
        EmsEspNumber(coordinator, "dhw_seltemp", "Warmwasser Solltemperatur",
            min_val=35, max_val=65, step=1,
            unit=UnitOfTemperature.CELSIUS, device_type=DEVICE_DHW,
            command_topic="boiler/wwseltemp",
            value_fn=lambda d: d["dhw"].set_temp if d["dhw"] else None),
        EmsEspNumber(coordinator, "hc1_flowtempmax", "HC1 VL Maximaltemperatur",
            min_val=30, max_val=85, step=1,
            unit=UnitOfTemperature.CELSIUS, device_type=DEVICE_HC,
            command_topic="thermostat/hc1/flowtempmax",
            value_fn=lambda d: d["thermostat"].hcs[1].flow_temp_max if d["thermostat"] and 1 in d["thermostat"].hcs else None),
        EmsEspNumber(coordinator, "hc1_flowtempmin", "HC1 VL Minimaltemperatur",
            min_val=10, max_val=40, step=1,
            unit=UnitOfTemperature.CELSIUS, device_type=DEVICE_HC,
            command_topic="thermostat/hc1/flowtempmin",
            value_fn=lambda d: d["thermostat"].hcs[1].flow_temp_min if d["thermostat"] and 1 in d["thermostat"].hcs else None),
        EmsEspNumber(coordinator, "hc1_heatslope", "HC1 Heizkurve Neigung",
            min_val=0.1, max_val=4.0, step=0.1,
            unit=None, device_type=DEVICE_HC,
            command_topic="thermostat/hc1/heatslope",
            value_fn=lambda d: d["thermostat"].hcs[1].heat_slope if d["thermostat"] and 1 in d["thermostat"].hcs else None),
        EmsEspNumber(coordinator, "hpmaxpower", "WP Maximalleistung",
            min_val=0, max_val=100, step=1,
            unit="%", device_type=DEVICE_BOILER,
            command_topic="boiler/hpmaxpower",
            value_fn=lambda d: d["boiler"].hp_max_power if d["boiler"] else None),
    ])


class EmsEspNumber(CoordinatorEntity, NumberEntity):
    def __init__(self, coordinator, key, name, min_val, max_val, step, unit, device_type, command_topic, value_fn):
        super().__init__(coordinator)
        self._key = key
        self._command_topic = command_topic
        self._value_fn = value_fn
        self._device_type = device_type
        self._attr_unique_id = f"{coordinator.entry_id}_{key}"
        self._attr_name = name
        self._attr_native_min_value = min_val
        self._attr_native_max_value = max_val
        self._attr_native_step = step
        self._attr_native_unit_of_measurement = unit
        self._attr_mode = NumberMode.BOX
        self._attr_has_entity_name = True

    @property
    def device_info(self):
        if self._device_type == DEVICE_DHW:
            return self.coordinator.dhw_device_info
        if self._device_type == DEVICE_HC:
            return self.coordinator.hc_device_info(1)
        return self.coordinator.boiler_device_info

    @property
    def native_value(self):
        if self.coordinator.data:
            return self._value_fn(self.coordinator.data)
        return None

    async def async_set_native_value(self, value: float) -> None:
        await self.coordinator.async_publish_command(
            self._command_topic,
            str(int(value)) if value == int(value) else str(value),
        )

    @property
    def available(self) -> bool:
        return self.coordinator.gateway_info.online
