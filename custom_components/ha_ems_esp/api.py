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

from .const import API_PATH_DEVICE_COMMAND, API_PATH_DEVICE_ENTITIES, API_PATH_SYSTEM_INFO

_LOGGER = logging.getLogger(__name__)

REQUEST_TIMEOUT = 10


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
        headers = {"Authorization": f"Bearer {self._api_token}"} if self._api_token else None
        try:
            async with asyncio.timeout(REQUEST_TIMEOUT):
                async with self._session.post(
                    url, json={"value": value}, headers=headers
                ) as response:
                    response.raise_for_status()
                    return await response.json(content_type=None)
        except (aiohttp.ClientError, asyncio.TimeoutError) as err:
            raise CannotConnect from err

    async def _get(self, path: str) -> Any:
        url = f"http://{self._host}{path}"
        try:
            async with asyncio.timeout(REQUEST_TIMEOUT):
                async with self._session.get(url) as response:
                    response.raise_for_status()
                    return await response.json(content_type=None)
        except (aiohttp.ClientError, asyncio.TimeoutError) as err:
            raise CannotConnect from err
