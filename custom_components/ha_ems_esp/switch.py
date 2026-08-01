"""Switch-Plattform fuer ha_ems_esp.

Schreibbare boolesche Entities aus /api/<device>/entities
(type == "boolean", writeable == true). Schreibpfad siehe dynamic_entity.py.
"""
from __future__ import annotations

from homeassistant.components.switch import SwitchEntity
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddEntitiesCallback

from .dynamic_entity import EmsDynamicEntity, async_setup_dynamic_platform
from .entity_factory import EmsEntityPlatform, coerce_bool


async def async_setup_entry(
    hass: HomeAssistant, entry: ConfigEntry, async_add_entities: AddEntitiesCallback
) -> None:
    async_setup_dynamic_platform(
        hass, entry, async_add_entities, EmsEntityPlatform.SWITCH, EmsDynamicSwitch
    )


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
