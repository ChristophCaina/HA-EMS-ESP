"""Climate entity for EMS-ESP heating circuits."""
from __future__ import annotations
from homeassistant.components.climate import (
    ClimateEntity,
    ClimateEntityFeature,
    HVACMode,
)
from homeassistant.config_entries import ConfigEntry
from homeassistant.const import UnitOfTemperature
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.helpers.update_coordinator import CoordinatorEntity

from .const import DOMAIN, DEVICE_HC, THERMOSTAT_MODES
from .coordinator import EmsEspCoordinator


EMS_TO_HA_HVAC: dict[str, HVACMode] = {
    "auto": HVACMode.AUTO,
    "day": HVACMode.HEAT,
    "manual": HVACMode.HEAT,
    "comfort": HVACMode.HEAT,
    "night": HVACMode.COOL,
    "eco": HVACMode.AUTO,
    "nofrost": HVACMode.OFF,
    "off": HVACMode.OFF,
    "holiday": HVACMode.OFF,
}

HA_TO_EMS_HVAC: dict[HVACMode, str] = {
    HVACMode.AUTO: "auto",
    HVACMode.HEAT: "day",
    HVACMode.COOL: "night",
    HVACMode.OFF: "nofrost",
}


async def async_setup_entry(
    hass: HomeAssistant,
    entry: ConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    coordinator: EmsEspCoordinator = hass.data[DOMAIN][entry.entry_id]
    async_add_entities([EmsEspClimate(coordinator, hc_id=1)])


class EmsEspClimate(CoordinatorEntity, ClimateEntity):
    """Climate entity representing one heating circuit."""

    _attr_temperature_unit = UnitOfTemperature.CELSIUS
    _attr_supported_features = (
        ClimateEntityFeature.TARGET_TEMPERATURE
    )
    _attr_hvac_modes = [HVACMode.AUTO, HVACMode.HEAT, HVACMode.COOL, HVACMode.OFF]
    _attr_min_temp = 5.0
    _attr_max_temp = 30.0
    _attr_target_temperature_step = 0.5
    _attr_has_entity_name = True

    def __init__(self, coordinator: EmsEspCoordinator, hc_id: int) -> None:
        super().__init__(coordinator)
        self._hc_id = hc_id
        self._attr_unique_id = f"{coordinator.entry_id}_climate_hc{hc_id}"
        self._attr_name = f"Heizkreis HC{hc_id}"

    @property
    def device_info(self):
        return self.coordinator.hc_device_info(self._hc_id)

    def _get_hc(self):
        if self.coordinator.data and self.coordinator.data["thermostat"]:
            return self.coordinator.data["thermostat"].hcs.get(self._hc_id)
        return None

    @property
    def current_temperature(self) -> float | None:
        hc = self._get_hc()
        return hc.cur_temp if hc else None

    @property
    def target_temperature(self) -> float | None:
        hc = self._get_hc()
        return hc.sel_temp if hc else None

    @property
    def hvac_mode(self) -> HVACMode:
        hc = self._get_hc()
        if hc and hc.mode:
            return EMS_TO_HA_HVAC.get(hc.mode.lower(), HVACMode.AUTO)
        return HVACMode.AUTO

    async def async_set_temperature(self, **kwargs) -> None:
        temp = kwargs.get("temperature")
        if temp is not None:
            await self.coordinator.async_publish_command(
                f"thermostat/hc{self._hc_id}/seltemp", str(temp)
            )

    async def async_set_hvac_mode(self, hvac_mode: HVACMode) -> None:
        ems_mode = HA_TO_EMS_HVAC.get(hvac_mode, "auto")
        await self.coordinator.async_publish_command(
            f"thermostat/hc{self._hc_id}/mode", ems_mode
        )

    @property
    def available(self) -> bool:
        return self.coordinator.gateway_info.online
