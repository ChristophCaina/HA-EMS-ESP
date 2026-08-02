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

Rate-Limiting (seit EMS-ESP 3.8.3): Die Firmware blockt jetzt zu viele
GET-Requests in kurzer Folge mit HTTP 429 ("block too many GET requests",
CHANGELOG #3104). Dagegen: api.py versucht bei 429 automatisch mit Backoff
erneut, und hier werden Anfragen innerhalb eines Poll-Zyklus zusaetzlich
mit kleinen Pausen entzerrt (statt sie im Bündel abzufeuern), plus die
seltenen Duschalarm-Einzelwerte laufen nur noch alle
EmsEspSystemCoordinator._EXTRA_SETTINGS_EVERY_N_POLLS Zyklen mit, nicht
bei jedem Poll.
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
        self._poll_count = 0

    # "circuit"-qualifizierte Settings, die NICHT Teil der /api/system/info
    # Sammel-Antwort sind, aber trotzdem in Diagnose-Sensoren landen sollen
    # (bestaetigt: showerAlertTrigger/showerAlertColdshot). Werden hier
    # zusaetzlich abgefragt und unter "settings" eingemischt, damit
    # gateway_diagnostics.py sie einheitlich lesen kann, egal ob ein Wert
    # aus der Sammel-Antwort oder einem Einzel-Aufruf kommt.
    #
    # Nur jeden EXTRA_SETTINGS_EVERY_N_POLLS-ten Zyklus abgefragt (nicht
    # bei jedem Poll) - das sind fast statische Konfigurationswerte, die
    # sich praktisch nie aendern, und zusaetzliche Requests bei jedem
    # 60s-Zyklus tragen unnoetig zum Anfrage-Aufkommen bei. Relevant seit
    # EMS-ESP 3.8.3 selbst GET-Anfragen in kurzer Folge blockt ("block too
    # many GET requests", CHANGELOG #3104).
    _EXTRA_SETTINGS = ("showerAlertTrigger", "showerAlertColdshot")
    _EXTRA_SETTINGS_EVERY_N_POLLS = 10

    async def _async_update_data(self) -> dict[str, Any]:
        try:
            system_info = await self._client.async_get_system_info()
        except CannotConnect as err:
            raise UpdateFailed(f"Gateway nicht erreichbar: {err}") from err

        # NICHT beim allerersten Refresh (poll_count == 0): reproduzierbar
        # bei jedem Reload fuehrten die Zusatzabfragen direkt neben dem
        # fast zeitgleichen ersten /api/system/info-Aufruf beider
        # Coordinators zu "Command failed: no 'settings' in system" im
        # EMS-ESP-Log (3.8.3). Init-Fenster bewusst frei halten - die
        # beiden Werte sind ohnehin fast statisch, ein paar Minuten
        # spaeter zum ersten Mal befuellt macht praktisch keinen Unterschied.
        if self._poll_count > 0 and self._poll_count % self._EXTRA_SETTINGS_EVERY_N_POLLS == 0:
            settings = system_info.setdefault("settings", {})
            for name in self._EXTRA_SETTINGS:
                await asyncio.sleep(1.0)  # groszuegiger Abstand, siehe Docstring oben
                try:
                    detail = await self._client.async_get_system_setting(
                        "settings", name
                    )
                except CannotConnect:
                    # Nicht kritisch fuer den Rest der Diagnose - einfach
                    # auslassen, naechster Zyklus versucht's erneut.
                    continue
                if isinstance(detail, dict) and "value" in detail:
                    settings[name] = detail["value"]
        elif self.data and "settings" in self.data:
            # In den uebersprungenen Zyklen die zuletzt bekannten Werte
            # erhalten, statt sie kommentarlos verschwinden zu lassen.
            system_info.setdefault("settings", {}).update(
                {
                    k: v
                    for k, v in self.data["settings"].items()
                    if k in self._EXTRA_SETTINGS
                }
            )

        self._poll_count += 1
        return system_info

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

    def __init__(
        self, hass: HomeAssistant, client: EmsEspApiClient, scan_interval_seconds: int
    ) -> None:
        super().__init__(
            hass,
            _LOGGER,
            name=f"{DOMAIN} structure",
            update_interval=timedelta(seconds=scan_interval_seconds),
        )
        self._client = client

    async def _async_update_data(self) -> dict[str, list[dict[str, Any]]]:
        try:
            system_info = await self._client.async_get_system_info()
            device_types = sorted(
                {d["type"] for d in system_info.get("devices", []) if d.get("type")}
            )
            previous = self.data or {}

            structure: dict[str, list[dict[str, Any]]] = {}
            for index, device_type in enumerate(device_types):
                if index > 0:
                    await asyncio.sleep(0.3)  # Anfragen entzerren, siehe coordinator.py Modul-Docstring
                fresh_entities = await self._client.async_get_device_entities(
                    device_type
                )
                previous_by_name = {
                    e.get("name"): e for e in previous.get(device_type, [])
                }
                merged_entities: list[dict[str, Any]] = []
                for entity in fresh_entities:
                    if "value" not in entity:
                        # Bestaetigt bei "custom" (Custom Entities): die
                        # REST-Sammel-Antwort liefert dafuer NIE einen
                        # "value" - ohne diesen Erhalt wuerde jeder Poll
                        # den zuletzt per MQTT/Schreibvorgang bekannten
                        # Wert stillschweigend loeschen.
                        name = entity.get("name")
                        old_value = previous_by_name.get(name, {}).get("value")
                        if old_value is not None:
                            entity = {**entity, "value": old_value}
                    merged_entities.append(entity)
                structure[device_type] = merged_entities
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
