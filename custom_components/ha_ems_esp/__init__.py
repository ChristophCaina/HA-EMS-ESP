"""Die ha_ems_esp Integration.

Config Flow, REST-Client, beide Struktur-/Diagnose-Coordinators, MQTT-Live-
Push und Repair-Issues fuer Verbindungsprobleme (MQTT und REST/Gateway)
stehen. Das Gateway wird als eigenes HA-Device registriert. select
(schreibbare enum-Entities) und climate (Thermostat-Sollwert) folgen noch,
siehe entity_factory.py Docstring.
"""
from __future__ import annotations

import logging

from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant, callback
from homeassistant.helpers import device_registry as dr
from homeassistant.helpers import issue_registry as ir

from .api import EmsEspApiClient
from .const import CONF_API_TOKEN, CONF_HOST, DOMAIN
from .coordinator import (
    EmsEspFirmwareCoordinator,
    EmsEspStructureCoordinator,
    EmsEspSystemCoordinator,
)
from .issues import gateway_unreachable_issue_id, mqtt_unavailable_issue_id
from .mqtt import async_setup_mqtt_listener

_LOGGER = logging.getLogger(__name__)

# TODO: select fuer schreibbare enum-Entities folgt, sobald die
# EMS-ESP API-Antwort fuer enum-Typen mit Optionsliste verifiziert ist
# (siehe entity_factory.py Docstring). climate (Thermostat-Sollwert)
# folgt ebenfalls noch als eigener Sonderfall.
PLATFORMS: list[str] = ["sensor", "binary_sensor", "number", "switch", "update"]


async def async_setup_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    """Richtet einen Config-Entry ein."""
    host = entry.data[CONF_HOST]
    client = EmsEspApiClient(hass, host, entry.options.get(CONF_API_TOKEN))

    system_coordinator = EmsEspSystemCoordinator(hass, client)
    structure_coordinator = EmsEspStructureCoordinator(hass, client)
    firmware_coordinator = EmsEspFirmwareCoordinator(hass)

    await system_coordinator.async_config_entry_first_refresh()
    await structure_coordinator.async_config_entry_first_refresh()
    # async_refresh() statt async_config_entry_first_refresh(): ein
    # GitHub-Ausfall/Rate-Limit soll den Rest der Integration nicht per
    # ConfigEntryNotReady blockieren - Firmware-Check ist rein informativ.
    await firmware_coordinator.async_refresh()

    _async_register_gateway_device(hass, entry, system_coordinator.data)

    hass.data.setdefault(DOMAIN, {})[entry.entry_id] = {
        "client": client,
        "system_coordinator": system_coordinator,
        "structure_coordinator": structure_coordinator,
        "firmware_coordinator": firmware_coordinator,
    }

    # Repair-Issue "Gateway nicht erreichbar": reagiert auf jeden Refresh
    # (Erfolg oder Fehlschlag) beider Coordinators - REST ist damit die
    # alleinige, selbstheilende Quelle fuer diesen Hinweis, unabhaengig
    # von MQTT. Wird NACH dem ersten (erzwungenermassen erfolgreichen,
    # sonst waere async_config_entry_first_refresh oben schon mit
    # ConfigEntryNotReady abgebrochen) Refresh registriert.
    @callback
    def _check_gateway_reachable() -> None:
        issue_id = gateway_unreachable_issue_id(entry)
        if system_coordinator.last_update_success and structure_coordinator.last_update_success:
            ir.async_delete_issue(hass, DOMAIN, issue_id)
        else:
            ir.async_create_issue(
                hass,
                DOMAIN,
                issue_id,
                is_fixable=False,
                severity=ir.IssueSeverity.ERROR,
                translation_key="gateway_unreachable",
                translation_placeholders={"title": entry.title, "host": host},
            )

    entry.async_on_unload(system_coordinator.async_add_listener(_check_gateway_reachable))
    entry.async_on_unload(structure_coordinator.async_add_listener(_check_gateway_reachable))

    if PLATFORMS:
        await hass.config_entries.async_forward_entry_setups(entry, PLATFORMS)

    try:
        await async_setup_mqtt_listener(hass, entry)
    except Exception:  # noqa: BLE001 - MQTT-Live-Updates sind optional/best-effort,
        # REST-Betrieb muss davon unabhaengig funktionieren (z.B. wenn HA's
        # MQTT-Integration gar nicht konfiguriert ist).
        _LOGGER.warning(
            "MQTT-Live-Updates konnten nicht eingerichtet werden - "
            "Werte bleiben ueber REST-Polling aktuell.",
            exc_info=True,
        )
        ir.async_create_issue(
            hass,
            DOMAIN,
            mqtt_unavailable_issue_id(entry),
            is_fixable=False,
            severity=ir.IssueSeverity.WARNING,
            translation_key="mqtt_unavailable",
            translation_placeholders={"title": entry.title},
        )
    else:
        # Laufende Ueberwachung (Heartbeat-Timeout, status-Topic) uebernimmt
        # mqtt.py selbst - hier nur der initiale Erfolgsfall.
        ir.async_delete_issue(hass, DOMAIN, mqtt_unavailable_issue_id(entry))

    entry.async_on_unload(entry.add_update_listener(_async_update_listener))
    return True


async def async_unload_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    """Entfernt einen Config-Entry wieder."""
    unload_ok = True
    if PLATFORMS:
        unload_ok = await hass.config_entries.async_unload_platforms(entry, PLATFORMS)
    if unload_ok:
        hass.data[DOMAIN].pop(entry.entry_id, None)
        ir.async_delete_issue(hass, DOMAIN, mqtt_unavailable_issue_id(entry))
        ir.async_delete_issue(hass, DOMAIN, gateway_unreachable_issue_id(entry))
    return unload_ok


async def _async_update_listener(hass: HomeAssistant, entry: ConfigEntry) -> None:
    """Wird ausgeloest, wenn Options (MQTT/Schreibpfad) im Options Flow geaendert wurden."""
    await hass.config_entries.async_reload(entry.entry_id)


def _async_register_gateway_device(
    hass: HomeAssistant, entry: ConfigEntry, system_info: dict
) -> None:
    """Legt das Gateway als eigenstaendiges HA-Device an.

    Alle spaeter erkannten EMS-Geraete (Boiler, Thermostat, ...) werden
    ueber via_device an diese Geraete-ID gehaengt.
    """
    device_registry = dr.async_get(hass)
    system = system_info.get("system", {})
    device_registry.async_get_or_create(
        config_entry_id=entry.entry_id,
        identifiers={(DOMAIN, entry.unique_id or entry.entry_id)},
        manufacturer="EMS-ESP",
        name=entry.title,
        model=system.get("model", "EMS-ESP Gateway"),
        hw_version=system.get("platform"),
        sw_version=system.get("version"),
        configuration_url=f"http://{entry.data[CONF_HOST]}",
    )
