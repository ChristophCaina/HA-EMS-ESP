"""Coordinators fuer ha_ems_esp.

Zwei getrennte Update-Zyklen, statt einem einzigen Coordinator:

- EmsEspSystemCoordinator: schneller Poll auf /api/system/info. Liefert die
  Diagnose-Daten fuer das Gateway-Device (Uptime, Heap, Bus-Status, ...) und
  laeuft unabhaengig davon, ob am Bus ueberhaupt etwas haengt. Das Payload
  enthaelt unter "devices" bereits eine Liste aller aktuell erkannten
  Geraete (type/name/entities-Anzahl) - das ist die Grundlage fuer die
  Struktur-Discovery, ein Scan ueber eine feste Geraeteliste ist nicht
  noetig.

- EmsEspStructureCoordinator: liest die "devices"-Liste aus /api/system/info
  und fragt fuer jeden dort gemeldeten Geraetetyp /api/<device>/entities ab.
  Erkennt so neu am Bus erschienene Geraete und neue, per Firmware-Update
  hinzugekommene Entities. Ergebnis ist die Grundlage fuer die (spaeter
  folgende) entity_factory.py.

Live-Werte laufen NICHT ueber diese Coordinators, sondern per MQTT-Push
(siehe geplantes mqtt.py) - das haelt die REST-Polls bewusst grob-taktig.
"""
from __future__ import annotations

import logging
from datetime import timedelta
from typing import Any

from homeassistant.core import HomeAssistant
from homeassistant.helpers.update_coordinator import DataUpdateCoordinator

from .api import EmsEspApiClient
from .const import (
    DEFAULT_STRUCTURE_SCAN_INTERVAL,
    DEFAULT_SYSTEM_INFO_SCAN_INTERVAL,
    DOMAIN,
)

_LOGGER = logging.getLogger(__name__)


class EmsEspSystemCoordinator(DataUpdateCoordinator[dict[str, Any]]):
    """Poll auf /api/system/info fuer Gateway-Diagnosedaten."""

    def __init__(self, hass: HomeAssistant, client: EmsEspApiClient) -> None:
        super().__init__(
            hass,
            _LOGGER,
            name=f"{DOMAIN} system info",
            update_interval=timedelta(seconds=DEFAULT_SYSTEM_INFO_SCAN_INTERVAL),
        )
        self._client = client
        # None = noch kein MQTT-Status empfangen (z.B. MQTT deaktiviert) -
        # dann zaehlt ausschliesslich der REST-Poll-Erfolg fuer available.
        # True/False kommt vom <base>/status LWT-Topic, siehe mqtt.py.
        self.mqtt_available: bool | None = None

    async def _async_update_data(self) -> dict[str, Any]:
        return await self._client.async_get_system_info()

    def device_types(self) -> list[str]:
        """Aktuell laut /api/system/info erkannte Geraetetypen (devices[].type)."""
        if not self.data:
            return []
        devices = self.data.get("devices", [])
        return sorted({d["type"] for d in devices if d.get("type")})


class EmsEspStructureCoordinator(DataUpdateCoordinator[dict[str, list[dict[str, Any]]]]):
    """Fragt /api/<device>/entities fuer jeden aktuell gemeldeten Geraetetyp ab.

    data ist ein dict {device_type: [entity, ...]}. Welche device_types
    ueberhaupt existieren, wird bei jedem Zyklus frisch aus
    /api/system/info -> "devices" gelesen (siehe _fetch_current_device_types),
    statt einer festen, geratenen Liste zu folgen.
    """

    def __init__(self, hass: HomeAssistant, client: EmsEspApiClient) -> None:
        super().__init__(
            hass,
            _LOGGER,
            name=f"{DOMAIN} structure",
            update_interval=timedelta(seconds=DEFAULT_STRUCTURE_SCAN_INTERVAL),
        )
        self._client = client
        self.mqtt_available: bool | None = None

    async def _async_update_data(self) -> dict[str, list[dict[str, Any]]]:
        system_info = await self._client.async_get_system_info()
        device_types = sorted(
            {d["type"] for d in system_info.get("devices", []) if d.get("type")}
        )

        structure: dict[str, list[dict[str, Any]]] = {}
        for device_type in device_types:
            structure[device_type] = await self._client.async_get_device_entities(
                device_type
            )
        return structure

    def known_devices(self) -> list[str]:
        """Geraetetypen, fuer die aktuell mindestens eine Entity gemeldet wird."""
        if not self.data:
            return []
        return [device_type for device_type, entities in self.data.items() if entities]
