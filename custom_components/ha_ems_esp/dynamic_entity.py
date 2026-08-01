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
from homeassistant.helpers import device_registry as dr
from homeassistant.helpers import entity_registry as er
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
    is_gateway_local,
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
            # Der Schreibversuch selbst ist fehlgeschlagen (anders als der
            # Race-Condition-Fall bei Erfolg, siehe _optimistic_update) -
            # hier gibt es keinen neuen Wert zum optimistisch Setzen, aber
            # der Cache koennte trotzdem veraltet sein. Ohne diesen Refresh
            # wuerde der zuletzt bekannte (evtl. laengst ueberholte) Wert
            # bis zum naechsten planmaessigen Poll (bis zu 5 Min) oder
            # einem manuellen Reload stehen bleiben.
            await self.coordinator.async_request_refresh()
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
    angelegt (siehe "known"-dict).

    Entfernt umgekehrt auch Entities, die die API nicht mehr liefert (z.B.
    eine auf dem Gateway geloeschte Custom Entity) - nicht nur als
    "nicht verfuegbar" haengen lassen, sondern aktiv aus der Entity-
    Registry entfernen. Wird dadurch ein Geraet leer (keine Entities auf
    keiner Plattform mehr), wird das Geraet ebenfalls entfernt. Das
    Gateway-Device selbst und Gateway-lokale Typen sind davon nie
    betroffen (siehe _cleanup_orphaned_devices/is_gateway_local).
    """
    data = hass.data[DOMAIN][entry.entry_id]
    coordinator: EmsEspStructureCoordinator = data["structure_coordinator"]
    known: dict[tuple[str, str], EmsDynamicEntity] = {}

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
            entity = entity_class(coordinator, entry, descriptor)
            known[ident] = entity
            new_entities.append(entity)
        if new_entities:
            async_add_entities(new_entities)

    def _remove_stale_entities() -> None:
        """Entfernt Entities, die die API nicht mehr liefert (z.B. eine auf
        dem Gateway geloeschte Custom Entity), statt sie fuer immer als
        "nicht verfuegbar" haengen zu lassen. Raeumt anschliessend auch
        Geraete auf, die dadurch keine Entities mehr haben.
        """
        current_idents = {
            (d.device_type, d.key) for d in _descriptors_for_platform()
        }
        stale_idents = set(known) - current_idents
        if not stale_idents:
            return

        entity_registry = er.async_get(hass)
        affected_device_types: set[str] = set()
        for ident in stale_idents:
            entity = known.pop(ident)
            if entity.entity_id and entity_registry.async_get(entity.entity_id):
                entity_registry.async_remove(entity.entity_id)
            affected_device_types.add(ident[0])

        _cleanup_orphaned_devices(affected_device_types)

    def _cleanup_orphaned_devices(device_types: set[str]) -> None:
        """Entfernt HA-Devices ohne verbleibende Entities.

        Prueft nur die von der gerade erfolgten Entfernung betroffenen
        Geraetetypen (nicht global) und ruehrt das Gateway-Device sowie
        Gateway-lokale Typen (temperaturesensor/analogsensor) NIE an -
        die haengen ja ohnehin am Gateway-Device, nicht an einem eigenen.
        """
        device_registry = dr.async_get(hass)
        entity_registry = er.async_get(hass)
        gateway_id = entry.unique_id or entry.entry_id

        for device_type in device_types:
            if is_gateway_local(device_type):
                continue
            device = device_registry.async_get_device(
                identifiers={(DOMAIN, f"{gateway_id}_{device_type}")}
            )
            if device is None:
                continue
            remaining = er.async_entries_for_device(
                entity_registry, device.id, include_disabled_entities=True
            )
            if not remaining:
                device_registry.async_remove_device(device.id)

    _add_new_entities()

    @callback
    def _handle_coordinator_update() -> None:
        _add_new_entities()
        _remove_stale_entities()

    entry.async_on_unload(coordinator.async_add_listener(_handle_coordinator_update))
