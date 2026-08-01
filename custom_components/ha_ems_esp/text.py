"""Text-Plattform fuer ha_ems_esp.

Schreibbare String-Entities aus /api/<device>/entities
(type == "string", writeable == true). Bestaetigt gegen echte Payloads von
Custom Entities (EMS-ESP "RAM-Wert"/"NVS-Wert" vom Datentyp String).

Wichtige Einschraenkung, bestaetigt mit echten Daten: EMS-ESP deklariert
Custom Entities IMMER als type=="string" - auch wenn eine numerische
Einheit (z.B. °C) gesetzt ist. EMS-ESP selbst erlaubt dann trotzdem Freitext
per API/MQTT (nur die eigene WebUI blockt Nicht-Zahlen). Damit wir nicht
versehentlich Datenmuell an ein Feld schicken, das erkennbar eine Zahl
erwartet, validieren wir: ist eine Einheit gesetzt, muss der Wert wie eine
Zahl aussehen.

Zwei Ebenen, beide aktiv:
- HA-eigenes "pattern"-Attribut: wird von HA Core serverseitig durchgesetzt
  (bestaetigt - anders als aeltere Community-Berichte vermuten liessen),
  liefert sofortiges visuelles Feedback (rote Markierung).
- Eigene Pruefung in async_set_value: greift als Absicherung fuer Pfade,
  die unseren Code trotzdem erreichen, und loest zusaetzlich einen
  sofortigen Refresh aus statt auf den naechsten planmaessigen Zyklus zu
  warten.

WICHTIG zum Verstehen, warum das kein "Bug" war, auch als "pattern" die
eigene Pruefung meist vorwegnimmt: Unsere Entities sind CoordinatorEntity-
basiert - JEDER Coordinator-Refresh (REST-Poll oder MQTT-Push) schreibt den
aktuellen Zustand automatisch, VOELLIG unabhaengig davon, ob vorher
ueberhaupt ein Schreibversuch stattfand oder abgelehnt wurde. Ein von HA
Core per "pattern" abgelehnter Wert ruehrt unseren Cache also nicht an -
der naechste reguläre Poll/Push korrigiert das von selbst, auch ganz ohne
Extra-Code. Der Refresh-Trigger unten ist nur fuer schnelleres Feedback,
nicht fuer die Korrektheit an sich notwendig.
"""
from __future__ import annotations

import re
from typing import Any

from homeassistant.components.text import TextEntity
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.exceptions import HomeAssistantError
from homeassistant.helpers.entity_platform import AddEntitiesCallback

from .dynamic_entity import EmsDynamicEntity, async_setup_dynamic_platform
from .entity_factory import EmsEntityPlatform

_NUMERIC_PATTERN_STR = r"^-?\d+(\.\d+)?$"
_NUMERIC_PATTERN = re.compile(_NUMERIC_PATTERN_STR)


async def async_setup_entry(
    hass: HomeAssistant, entry: ConfigEntry, async_add_entities: AddEntitiesCallback
) -> None:
    async_setup_dynamic_platform(
        hass, entry, async_add_entities, EmsEntityPlatform.TEXT, EmsDynamicText
    )


class EmsDynamicText(EmsDynamicEntity, TextEntity):
    """Schreibbare String-Entity, z.B. ein EMS-ESP Custom-Entity-RAM-/NVS-Wert."""

    def __init__(self, coordinator, entry, descriptor) -> None:
        super().__init__(coordinator, entry, descriptor)
        if descriptor.unit:
            self._attr_pattern = _NUMERIC_PATTERN_STR

    @property
    def native_value(self) -> Any:
        raw = self._current_raw()
        if raw is None:
            return None
        value = raw.get("value")
        return None if value is None else str(value)

    async def async_set_value(self, value: str) -> None:
        value = value.strip()
        if self._descriptor.unit and not _NUMERIC_PATTERN.match(value):
            # Sofortiger Refresh statt auf den naechsten planmaessigen
            # Zyklus zu warten - reine Komfortverbesserung, nicht
            # notwendig fuer Korrektheit (siehe Modul-Docstring).
            await self.coordinator.async_request_refresh()
            raise HomeAssistantError(
                f"'{value}' ist keine gültige Zahl für {self.name} "
                f"(Einheit: {self._descriptor.unit}). EMS-ESP deklariert diese "
                f"Entity zwar technisch als Freitext, aber mit gesetzter "
                f"Einheit wird ein numerischer Wert erwartet."
            )
        await self._async_write_value(value)
