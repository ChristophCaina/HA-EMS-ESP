"""Number-Plattform fuer ha_ems_esp.

Schreibbare numerische Entities aus /api/<device>/entities
(type == "number", writeable == true). Schreibpfad siehe dynamic_entity.py.
"""
from __future__ import annotations

from typing import Any

from homeassistant.components.number import NumberDeviceClass, NumberEntity
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddEntitiesCallback

from .dynamic_entity import EmsDynamicEntity, async_setup_dynamic_platform
from .entity_factory import EmsEntityDescriptor, EmsEntityPlatform

# Fallback-Wertebereich, falls die API keine min/max liefert (z.B. manche
# Sollwert-Entities). Bewusst grosszuegig gewaehlt - besser ein zu weiter
# Bereich als eine Entity, die sich gar nicht anlegen laesst. Bei echten
# Boiler/Waermepumpe-Daten nochmal gegenpruefen.
_FALLBACK_MIN = -1000.0
_FALLBACK_MAX = 1000.0


async def async_setup_entry(
    hass: HomeAssistant, entry: ConfigEntry, async_add_entities: AddEntitiesCallback
) -> None:
    async_setup_dynamic_platform(
        hass, entry, async_add_entities, EmsEntityPlatform.NUMBER, EmsDynamicNumber
    )


class EmsDynamicNumber(EmsDynamicEntity, NumberEntity):
    """Schreibbare numerische Entity, z.B. Sollwerte oder GPIO-Ausgaenge."""

    def __init__(self, coordinator, entry: ConfigEntry, descriptor: EmsEntityDescriptor) -> None:
        super().__init__(coordinator, entry, descriptor)
        self._attr_native_unit_of_measurement = descriptor.unit
        self._attr_native_min_value = (
            descriptor.min_value if descriptor.min_value is not None else _FALLBACK_MIN
        )
        self._attr_native_max_value = (
            descriptor.max_value if descriptor.max_value is not None else _FALLBACK_MAX
        )
        if descriptor.device_class_hint:
            try:
                self._attr_device_class = NumberDeviceClass(descriptor.device_class_hint)
            except ValueError:
                pass

    @property
    def native_value(self) -> Any:
        raw = self._current_raw()
        return raw.get("value") if raw else None

    async def async_set_native_value(self, value: float) -> None:
        await self._async_write_value(value)
