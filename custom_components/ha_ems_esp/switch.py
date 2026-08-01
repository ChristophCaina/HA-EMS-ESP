"""Switch-Plattform fuer ha_ems_esp.

Zwei Quellen:
- Statische Gateway-Einstellungen (Duschtimer/-alarm, siehe
  gateway_settings.py) - REST-Schreibpfad ueber async_post_system_setting,
  bestaetigt gegen echte Tests.
- Dynamische, schreibbare boolesche Entities aus /api/<device>/entities
  (type == "boolean", writeable == true). Schreibpfad siehe
  dynamic_entity.py.
"""
from __future__ import annotations

from typing import Any

from homeassistant.components.switch import SwitchEntity
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.exceptions import HomeAssistantError
from homeassistant.helpers.entity import DeviceInfo
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.helpers.update_coordinator import CoordinatorEntity

from .api import CannotConnect, EmsEspApiClient
from .const import DOMAIN
from .coordinator import EmsEspSystemCoordinator
from .dynamic_entity import EmsDynamicEntity, async_setup_dynamic_platform
from .entity_factory import EmsEntityPlatform, coerce_bool
from .gateway_settings import GATEWAY_SWITCHES, GatewaySwitchDescription


async def async_setup_entry(
    hass: HomeAssistant, entry: ConfigEntry, async_add_entities: AddEntitiesCallback
) -> None:
    data = hass.data[DOMAIN][entry.entry_id]
    system_coordinator: EmsEspSystemCoordinator = data["system_coordinator"]

    async_add_entities(
        GatewaySettingSwitch(system_coordinator, entry, description)
        for description in GATEWAY_SWITCHES
    )

    async_setup_dynamic_platform(
        hass, entry, async_add_entities, EmsEntityPlatform.SWITCH, EmsDynamicSwitch
    )


class GatewaySettingSwitch(CoordinatorEntity[EmsEspSystemCoordinator], SwitchEntity):
    """Schreibbare Gateway-Einstellung, z.B. Duschtimer/-alarm."""

    _attr_has_entity_name = True

    def __init__(
        self,
        coordinator: EmsEspSystemCoordinator,
        entry: ConfigEntry,
        description: GatewaySwitchDescription,
    ) -> None:
        super().__init__(coordinator)
        self._entry = entry
        self._description = description
        self._attr_unique_id = f"{entry.unique_id or entry.entry_id}_{description.key}"
        self._attr_name = description.name
        self._attr_icon = description.icon
        self._attr_entity_category = description.entity_category
        self._attr_device_info = DeviceInfo(
            identifiers={(DOMAIN, entry.unique_id or entry.entry_id)}
        )

    @property
    def is_on(self) -> bool | None:
        merged = self.coordinator.merged_data()
        if not merged:
            return None
        return coerce_bool(self._description.value_fn(merged))

    async def async_turn_on(self, **kwargs: Any) -> None:
        await self._async_write(True)

    async def async_turn_off(self, **kwargs: Any) -> None:
        await self._async_write(False)

    async def _async_write(self, value: bool) -> None:
        client: EmsEspApiClient = self.hass.data[DOMAIN][self._entry.entry_id]["client"]
        try:
            await client.async_post_system_setting(
                self._description.circuit, self._description.key, value
            )
        except CannotConnect as err:
            raise HomeAssistantError(
                f"Konnte {self._description.key} nicht setzen"
            ) from err
        await self.coordinator.async_request_refresh()


class EmsDynamicSwitch(EmsDynamicEntity, SwitchEntity):
    """Schreibbare boolesche Entity."""

    @property
    def is_on(self) -> bool | None:
        raw = self._current_raw()
        if raw is None:
            return None
        return coerce_bool(raw.get("value"))

    async def async_turn_on(self, **kwargs) -> None:
        await self._async_write_value(1 if self._descriptor.numeric_bool else True)

    async def async_turn_off(self, **kwargs) -> None:
        await self._async_write_value(0 if self._descriptor.numeric_bool else False)
