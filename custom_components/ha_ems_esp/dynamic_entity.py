"""Gemeinsame Basis fuer dynamisch aus /api/<device>/entities erzeugte Entities.

Deckt sensor/binary_sensor/number/switch ab - alle lesen ihren aktuellen
Wert aus EmsEspStructureCoordinator.data (device_type -> Liste roher
API-Entity-Dicts inkl. "value"). Das ist bewusst der Struktur-Coordinator,
NICHT ein separater Live-Wert-Kanal - Live-Updates per MQTT-Push folgen
noch (siehe Konzept-Absprache), bis dahin sind Werte hoechstens
DEFAULT_STRUCTURE_SCAN_INTERVAL Sekunden alt.

Schreibpfad (number/switch) nutzt aktuell ausschliesslich REST-POST
(EmsEspApiClient.async_post_command). Der MQTT-Schreibpfad ist als Option
im Config/Options Flow bereits vorgesehen, aber noch nicht implementiert -
write_mode == "mqtt" wirft deshalb bewusst einen klaren Fehler statt still
nichts zu tun.
"""
from __future__ import annotations

import logging
from typing import Any

from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant, callback
from homeassistant.exceptions import HomeAssistantError
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.helpers.update_coordinator import CoordinatorEntity

from .api import CannotConnect, EmsEspApiClient
from .const import (
    CONF_WRITE_MODE,
    DOMAIN,
    WRITE_MODE_BOTH,
    WRITE_MODE_DEFAULT,
    WRITE_MODE_MQTT,
    WRITE_MODE_REST,
)
from .coordinator import EmsEspStructureCoordinator
from .entity_factory import (
    EmsEntityDescriptor,
    EmsEntityPlatform,
    build_entity_descriptors,
    device_info_for,
)
from .mqtt import async_publish_command

_LOGGER = logging.getLogger(__name__)


class EmsDynamicEntity(CoordinatorEntity[EmsEspStructureCoordinator]):
    """Basisklasse: liest ihren aktuellen Rohwert aus dem Struktur-Coordinator."""

    _attr_has_entity_name = True

    def __init__(
        self,
        coordinator: EmsEspStructureCoordinator,
        entry: ConfigEntry,
        descriptor: EmsEntityDescriptor,
    ) -> None:
        super().__init__(coordinator)
        self._entry = entry
        self._descriptor = descriptor
        self.device_type = descriptor.device_type
        self.entity_key = descriptor.key
        self._attr_unique_id = (
            f"{entry.unique_id or entry.entry_id}_{descriptor.unique_id_suffix}"
        )
        self._attr_name = descriptor.display_name
        self._attr_entity_category = descriptor.entity_category
        self._attr_device_info = device_info_for(descriptor.device_type, entry)

    def _current_raw(self) -> dict[str, Any] | None:
        if not self.coordinator.data:
            return None
        for entity in self.coordinator.data.get(self.device_type, []):
            if entity.get("name") == self.entity_key:
                return entity
        return None

    @property
    def available(self) -> bool:
        if self.coordinator.mqtt_available is False:
            return False
        return super().available and self._current_raw() is not None

    async def _async_write_value(self, value: Any) -> None:
        """Schreibt einen Wert - per REST, MQTT oder beidem, je nach write_mode.

        Bei write_mode="both" werden beide Pfade versucht; ein Fehler wird
        nur geworfen, wenn ALLE versuchten Pfade fehlschlagen (Redundanz,
        kein reines Fallback-Verhalten).
        """
        write_mode = self._entry.options.get(CONF_WRITE_MODE, WRITE_MODE_DEFAULT)
        _LOGGER.debug(
            "Schreibe %s/%s = %r (konfigurierter write_mode=%r, entry.options=%r)",
            self.device_type,
            self.entity_key,
            value,
            write_mode,
            dict(self._entry.options),
        )

        errors: list[str] = []
        successes = 0

        if write_mode in (WRITE_MODE_REST, WRITE_MODE_BOTH):
            client: EmsEspApiClient = self.hass.data[DOMAIN][self._entry.entry_id]["client"]
            try:
                await client.async_post_command(self.device_type, self.entity_key, value)
                successes += 1
            except CannotConnect as err:
                errors.append(f"REST fehlgeschlagen: {err}")

        if write_mode in (WRITE_MODE_MQTT, WRITE_MODE_BOTH):
            try:
                await async_publish_command(
                    self.hass, self._entry, self.device_type, self.entity_key, value
                )
                successes += 1
            except HomeAssistantError as err:
                errors.append(f"MQTT fehlgeschlagen: {err}")

        if successes == 0:
            raise HomeAssistantError(
                f"Kommando an {self.device_type}/{self.entity_key} fehlgeschlagen: "
                + "; ".join(errors)
            )

        self._optimistic_update(value)

    def _optimistic_update(self, value: Any) -> None:
        """Setzt den geschriebenen Wert sofort im Coordinator-Cache.

        Bewusst KEIN coordinator.async_request_refresh() hier: das wuerde
        sofort einen REST-Poll ausloesen, der oft noch den alten Wert
        liefert (das Geraet braucht einen Moment, um den Schreibbefehl zu
        verarbeiten) - das UI wuerde kurz auf den alten Wert zurueckfallen,
        bevor der MQTT-Live-Push (siehe mqtt.py) den korrekten neuen Wert
        nachliefert. Ein tatsaechlich abweichender Geraetezustand wird
        durch den naechsten MQTT-Push oder REST-Poll ohnehin automatisch
        korrigiert (self-healing, gleiches Prinzip wie in mqtt.py).
        """
        current = self.coordinator.data or {}
        entities = current.get(self.device_type)
        if entities is None:
            return

        updated_entities = [dict(entity) for entity in entities]
        for entity in updated_entities:
            if entity.get("name") == self.entity_key:
                entity["value"] = value
                break

        new_data = dict(current)
        new_data[self.device_type] = updated_entities
        self.coordinator.async_set_updated_data(new_data)


def async_setup_dynamic_platform(
    hass: HomeAssistant,
    entry: ConfigEntry,
    async_add_entities: AddEntitiesCallback,
    platform: EmsEntityPlatform,
    entity_class: type[EmsDynamicEntity],
) -> None:
    """Registriert alle Entities einer Plattform aus dem Struktur-Coordinator.

    Legt initial vorhandene Entities an und beobachtet danach den
    Coordinator, um neu auftauchende Geraete/Entities (z.B. wenn die
    Waermepumpe erstmals am Bus erscheint) ohne HA-Neustart
    nachzuregistrieren. Bereits erzeugte Entities werden nicht doppelt
    angelegt (siehe "known"-Set).
    """
    data = hass.data[DOMAIN][entry.entry_id]
    coordinator: EmsEspStructureCoordinator = data["structure_coordinator"]
    known: set[tuple[str, str]] = set()

    def _descriptors_for_platform() -> list[EmsEntityDescriptor]:
        if not coordinator.data:
            return []
        result: list[EmsEntityDescriptor] = []
        for device_type, entities in coordinator.data.items():
            result.extend(
                d
                for d in build_entity_descriptors(device_type, entities)
                if d.platform == platform
            )
        return result

    def _add_new_entities() -> None:
        new_entities = []
        for descriptor in _descriptors_for_platform():
            ident = (descriptor.device_type, descriptor.key)
            if ident in known:
                continue
            known.add(ident)
            new_entities.append(entity_class(coordinator, entry, descriptor))
        if new_entities:
            async_add_entities(new_entities)

    _add_new_entities()

    @callback
    def _handle_coordinator_update() -> None:
        _add_new_entities()

    entry.async_on_unload(coordinator.async_add_listener(_handle_coordinator_update))
