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
  hinzugekommene Entities. Ergebnis ist die Grundlage fuer entity_factory.py.

Live-Werte laufen zusaetzlich per MQTT-Push (siehe mqtt.py) - das haelt die
REST-Polls bewusst grob-taktig.

Verfuegbarkeit ist bewusst ausschliesslich REST-Poll-getrieben
(coordinator.last_update_success, Standardverhalten von CoordinatorEntity).
Ein fruehes Design hatte zusaetzlich ein MQTT-Status-Flag, das Entities hart
auf "nicht verfuegbar" gesetzt hat, sobald der <base>/status Topic
"offline" meldete - das fuehrte aber dazu, dass alles dauerhaft
"nicht verfuegbar" blieb, wenn MQTT auf dem Gateway bewusst deaktiviert
war, obwohl REST weiterhin einwandfrei funktionierte (MQTT-Offline heisst
nicht zwangslaeufig Geraet-Offline). Stattdessen loest mqtt.py bei einem
MQTT-Offline-Signal jetzt einen sofortigen REST-Request aus
(async_request_refresh) - Verfuegbarkeit bleibt danach korrekt
selbstheilend allein an REST haengen.
"""
from __future__ import annotations

import asyncio
import copy
import logging
from datetime import timedelta
from typing import Any

import aiohttp

from homeassistant.core import HomeAssistant
from homeassistant.helpers.aiohttp_client import async_get_clientsession
from homeassistant.helpers.update_coordinator import DataUpdateCoordinator, UpdateFailed

from .api import CannotConnect, EmsEspApiClient
from .const import (
    DEFAULT_FIRMWARE_CHECK_INTERVAL,
    DEFAULT_STRUCTURE_SCAN_INTERVAL,
    DEFAULT_SYSTEM_INFO_SCAN_INTERVAL,
    DOMAIN,
    GITHUB_LATEST_RELEASE_URL,
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
        # Persistente MQTT-Werte (heartbeat/info), die es in REST gar
        # nicht gibt (z.B. bootTime) oder die zwischen REST-Polls aktuell
        # gehalten werden sollen. WICHTIG: self.data wird bei jedem
        # erfolgreichen REST-Poll komplett ersetzt (_async_update_data) -
        # ein direktes Reinmischen von MQTT-Werten in self.data wuerde
        # beim naechsten Poll wieder verloren gehen. Deshalb getrennt
        # gehalten und erst in merged_data() zusammengefuehrt.
        self.mqtt_overlay: dict[str, dict[str, Any]] = {}

    async def _async_update_data(self) -> dict[str, Any]:
        try:
            return await self._client.async_get_system_info()
        except CannotConnect as err:
            raise UpdateFailed(f"Gateway nicht erreichbar: {err}") from err

    def device_types(self) -> list[str]:
        """Aktuell laut /api/system/info erkannte Geraetetypen (devices[].type)."""
        if not self.data:
            return []
        devices = self.data.get("devices", [])
        return sorted({d["type"] for d in devices if d.get("type")})

    def merged_data(self) -> dict[str, Any]:
        """REST-Daten (self.data) mit dem persistenten MQTT-Overlay kombiniert.

        MQTT-Werte gewinnen bei Ueberschneidungen (sie sind per Push
        tendenziell aktueller als der letzte REST-Poll). Von
        gateway_diagnostics.py value_fn-Lambdas statt self.data zu nutzen.
        """
        merged = copy.deepcopy(self.data) if self.data else {}
        for section, values in self.mqtt_overlay.items():
            merged.setdefault(section, {}).update(values)
        return merged


class EmsEspStructureCoordinator(DataUpdateCoordinator[dict[str, list[dict[str, Any]]]]):
    """Fragt /api/<device>/entities fuer jeden aktuell gemeldeten Geraetetyp ab.

    data ist ein dict {device_type: [entity, ...]}. Welche device_types
    ueberhaupt existieren, wird bei jedem Zyklus frisch aus
    /api/system/info -> "devices" gelesen, statt einer festen, geratenen
    Liste zu folgen.
    """

    def __init__(self, hass: HomeAssistant, client: EmsEspApiClient) -> None:
        super().__init__(
            hass,
            _LOGGER,
            name=f"{DOMAIN} structure",
            update_interval=timedelta(seconds=DEFAULT_STRUCTURE_SCAN_INTERVAL),
        )
        self._client = client

    async def _async_update_data(self) -> dict[str, list[dict[str, Any]]]:
        try:
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
        except CannotConnect as err:
            raise UpdateFailed(f"Gateway nicht erreichbar: {err}") from err

    def known_devices(self) -> list[str]:
        """Geraetetypen, fuer die aktuell mindestens eine Entity gemeldet wird."""
        if not self.data:
            return []
        return [device_type for device_type, entities in self.data.items() if entities]


class EmsEspFirmwareCoordinator(DataUpdateCoordinator[dict[str, Any] | None]):
    """Prueft periodisch die neueste EMS-ESP32-Firmware-Version auf GitHub.

    Rein informativ - siehe update.py Docstring, warum das automatische
    Flashen bewusst NICHT gebaut wird (Risiko eines Bricks bei falschem
    Board-Profil/falscher Binary-Variante).

    Nutzt async_refresh() statt async_config_entry_first_refresh() beim
    Setup (siehe __init__.py) - ein GitHub-Ausfall/Rate-Limit soll nicht
    den Rest der Integration blockieren.
    """

    def __init__(self, hass: HomeAssistant) -> None:
        super().__init__(
            hass,
            _LOGGER,
            name=f"{DOMAIN} firmware",
            update_interval=timedelta(seconds=DEFAULT_FIRMWARE_CHECK_INTERVAL),
        )
        self._session = async_get_clientsession(hass)

    async def _async_update_data(self) -> dict[str, Any] | None:
        try:
            async with asyncio.timeout(10):
                async with self._session.get(
                    GITHUB_LATEST_RELEASE_URL,
                    headers={"Accept": "application/vnd.github+json"},
                ) as response:
                    if response.status == 404:
                        # Kein "latest"-Release gefunden (z.B. nur Pre-Releases) -
                        # kein Fehler, einfach keine Update-Info verfuegbar.
                        return None
                    response.raise_for_status()
                    return await response.json()
        except (aiohttp.ClientError, asyncio.TimeoutError) as err:
            raise UpdateFailed(f"GitHub-Abfrage fehlgeschlagen: {err}") from err
