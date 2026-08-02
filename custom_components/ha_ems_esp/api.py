"""Duenner REST-Client fuer die EMS-ESP API.

Wird sowohl vom Config Flow (Verbindungs-Validierung) als auch von den
Coordinators (Struktur-Discovery, Diagnose-Werte, REST-Schreibpfad) genutzt,
damit die HTTP-Logik nur an einer Stelle existiert.

API-Referenz: https://emsesp.org/Commands
"""
from __future__ import annotations

import asyncio
import logging
from typing import Any

import aiohttp
from homeassistant.core import HomeAssistant
from homeassistant.helpers.aiohttp_client import async_get_clientsession

from .const import (
    API_PATH_DEVICE_COMMAND,
    API_PATH_DEVICE_ENTITIES,
    API_PATH_SYSTEM_INFO,
    API_PATH_SYSTEM_SETTING,
)

_LOGGER = logging.getLogger(__name__)

REQUEST_TIMEOUT = 10
# EMS-ESP 3.8.3+ blockt zu viele GET-Requests in kurzer Folge mit HTTP 429
# (CHANGELOG "block too many GET requests" #3104). Statt das sofort als
# "Gateway nicht erreichbar" zu werten, kurz warten und erneut versuchen.
_MAX_RETRIES_ON_RATE_LIMIT = 2
_RATE_LIMIT_BACKOFF_SECONDS = 2.0


class CannotConnect(Exception):
    """EMS-ESP war unter der angegebenen Host-Adresse nicht erreichbar."""


class EmsEspApiClient:
    """Kapselt alle REST-Aufrufe gegen ein EMS-ESP Gateway.

    api_token wird nur fuer schreibende Aufrufe (POST) als
    "Authorization: Bearer <token>" Header mitgeschickt. Lesende Aufrufe
    (GET) sind laut EMS-ESP-Doku immer oeffentlich, auch wenn Access-Token-
    Pruefung aktiv ist - dort wird kein Header benoetigt.
    """

    def __init__(self, hass: HomeAssistant, host: str, api_token: str | None = None) -> None:
        self._session = async_get_clientsession(hass)
        self._host = host
        self._api_token = api_token or None

    @property
    def host(self) -> str:
        return self._host

    async def async_get_system_info(self) -> dict[str, Any]:
        """GET /api/system/info - Gateway-Diagnosedaten, unabhaengig vom Bus-Zustand."""
        return await self._get(API_PATH_SYSTEM_INFO)

    async def async_get_device_entities(self, device: str) -> list[dict[str, Any]]:
        """GET /api/<device>/entities - Liste aller Entities eines EMS-Geraets.

        Liefert eine leere Liste, solange kein Geraet dieses Typs am Bus
        erkannt wurde (das ist bei einem frisch angeschlossenen Gateway
        ohne Wärmepumpe der Normalfall, kein Fehler).

        Die reale Antwort ist ein Objekt {kurzname: {details}}, nicht eine
        Liste (bestaetigt gegen echte analogsensor/temperaturesensor
        Payloads) - wir normalisieren hier auf eine Liste von Detail-Dicts,
        damit der Rest der Integration nicht zwischen beiden Formen
        unterscheiden muss.
        """
        result = await self._get(API_PATH_DEVICE_ENTITIES.format(device=device))
        if isinstance(result, dict):
            return list(result.values())
        if isinstance(result, list):
            return result
        return []

    async def async_get_system_setting(self, circuit: str, name: str) -> dict[str, Any]:
        """GET /api/system/<circuit>/<name> - Einzelwert einer "circuit"-
        qualifizierten System-Einstellung, die NICHT Teil der Sammel-Antwort
        von /api/system/info ist (bestaetigt bei showerAlertTrigger/
        showerAlertColdshot).
        """
        return await self._get(API_PATH_SYSTEM_SETTING.format(circuit=circuit, name=name))

    async def async_post_command(
        self, device: str, command: str, value: Any
    ) -> dict[str, Any]:
        """POST /api/<device>/<command> - synchroner Schreibpfad.

        Wird genutzt, wenn write_mode "rest" oder "both" ist. Schickt den
        Access Token mit, falls konfiguriert - EMS-ESP verlangt diesen fuer
        POST-Kommandos, sofern "Bypass Access Token authorization" auf dem
        Gateway nicht aktiviert ist.
        """
        url = f"http://{self._host}{API_PATH_DEVICE_COMMAND.format(device=device, command=command)}"
        return await self._post(url, value)

    async def async_post_system_setting(
        self, circuit: str, name: str, value: Any
    ) -> dict[str, Any]:
        """POST /api/system/<circuit>/<name> - Schreibpfad fuer "circuit"-
        qualifizierte System-Einstellungen aus /api/system/entities (z.B.
        "settings.showerTimer" -> circuit="settings", name="showerTimer").

        ANDERER URL-Aufbau als async_post_command (zusaetzliches Circuit-
        Pfadsegment) - bestaetigt gegen echte Tests fuer circuit="settings".
        """
        url = f"http://{self._host}{API_PATH_SYSTEM_SETTING.format(circuit=circuit, name=name)}"
        return await self._post(url, value)

    async def _post(self, url: str, value: Any) -> dict[str, Any]:
        headers = {"Authorization": f"Bearer {self._api_token}"} if self._api_token else None
        return await self._request("POST", url, json={"value": value}, headers=headers)

    async def _get(self, path: str) -> Any:
        url = f"http://{self._host}{path}"
        return await self._request("GET", url)

    async def _request(self, method: str, url: str, **kwargs: Any) -> Any:
        """Fuehrt einen HTTP-Request aus, mit Retry-Backoff bei 429.

        Bestaetigt ab EMS-ESP 3.8.3: das Gateway blockt jetzt selbst zu
        viele GET-Requests in kurzer Folge ("block too many GET requests",
        CHANGELOG #3104) mit HTTP 429. Statt das sofort als "Gateway nicht
        erreichbar" zu werten, kurz warten (respektiert einen etwaigen
        Retry-After Header) und erneut versuchen.
        """
        for attempt in range(_MAX_RETRIES_ON_RATE_LIMIT + 1):
            try:
                async with asyncio.timeout(REQUEST_TIMEOUT):
                    async with self._session.request(method, url, **kwargs) as response:
                        if response.status == 429:
                            if attempt >= _MAX_RETRIES_ON_RATE_LIMIT:
                                raise CannotConnect(
                                    "429 Too Many Requests (auch nach Wiederholungen)"
                                )
                            retry_after = response.headers.get("Retry-After", "")
                            delay = (
                                float(retry_after)
                                if retry_after.replace(".", "", 1).isdigit()
                                else _RATE_LIMIT_BACKOFF_SECONDS * (attempt + 1)
                            )
                            _LOGGER.debug(
                                "429 von %s - warte %.1fs und versuche erneut (%d/%d)",
                                url,
                                delay,
                                attempt + 1,
                                _MAX_RETRIES_ON_RATE_LIMIT,
                            )
                            await asyncio.sleep(delay)
                            continue
                        response.raise_for_status()
                        return await response.json(content_type=None)
            except asyncio.TimeoutError as err:
                raise CannotConnect(f"Zeitüberschreitung nach {REQUEST_TIMEOUT}s") from err
            except aiohttp.ClientError as err:
                raise CannotConnect(str(err) or repr(err)) from err

        # Unerreichbar (die 429-Ablehnung oben wirft im letzten Versuch
        # bereits), aber als Absicherung gegen stillschweigendes None.
        raise CannotConnect("429 Too Many Requests (auch nach Wiederholungen)")
