"""Config flow fuer ha_ems_esp.

Setup-Schritt fragt nur noch den REST-Host ab und validiert ihn gegen
/api/system/info. Boiler/Thermostat/etc. werden NICHT mehr im Config Flow
abgefragt - die entstehen dynamisch zur Laufzeit, sobald sie am Bus
erscheinen (siehe coordinator.py).

MQTT-Einstellungen (Base Topic, Discovery Prefix/Enabled) und der
Schreibpfad fuer Kommandos sind sowohl im initialen Setup als auch
nachtraeglich ueber den Options Flow konfigurierbar.
"""
from __future__ import annotations

import logging
from typing import Any

import voluptuous as vol

from homeassistant import config_entries
from homeassistant.data_entry_flow import FlowResult
from homeassistant.helpers import selector
from homeassistant.helpers.service_info.zeroconf import ZeroconfServiceInfo

from .api import CannotConnect, EmsEspApiClient
from .const import (
    CONF_API_TOKEN,
    CONF_HOST,
    CONF_MQTT_BASE_TOPIC,
    CONF_MQTT_DISCOVERY_ENABLED,
    CONF_MQTT_DISCOVERY_PREFIX,
    CONF_MQTT_HEARTBEAT_TIMEOUT,
    CONF_WRITE_MODE,
    DEFAULT_MQTT_BASE_TOPIC,
    DEFAULT_MQTT_DISCOVERY_ENABLED,
    DEFAULT_MQTT_DISCOVERY_PREFIX,
    DEFAULT_MQTT_HEARTBEAT_TIMEOUT,
    DOMAIN,
    WRITE_MODE_DEFAULT,
    WRITE_MODES,
)

_LOGGER = logging.getLogger(__name__)


def _build_unique_id(host: str, system_info: dict[str, Any]) -> str:
    """Leitet eine stabile unique_id ab.

    EMS-ESP liefert unter mqtt.clientID einen aus der Chip-ID abgeleiteten,
    stabilen Bezeichner (z.B. "esp32-2482c34c") - das ist auch dann
    vorhanden, wenn MQTT (noch) nicht aktiviert ist. Fallback ist der Host,
    falls dieses Feld mal fehlen sollte.
    """
    mqtt_client_id = system_info.get("mqtt", {}).get("clientID")
    if mqtt_client_id:
        return f"{DOMAIN}_{mqtt_client_id}"
    return f"{DOMAIN}_{host}"


def _mqtt_schema(defaults: dict[str, Any] | None = None) -> dict[Any, Any]:
    """Gemeinsames Schema-Fragment fuer MQTT-, Schreibpfad- und Token-Optionen."""
    defaults = defaults or {}
    return {
        vol.Optional(
            CONF_API_TOKEN,
            default=defaults.get(CONF_API_TOKEN, ""),
        ): selector.TextSelector(
            selector.TextSelectorConfig(type=selector.TextSelectorType.PASSWORD)
        ),
        vol.Optional(
            CONF_MQTT_BASE_TOPIC,
            default=defaults.get(CONF_MQTT_BASE_TOPIC, DEFAULT_MQTT_BASE_TOPIC),
        ): str,
        vol.Optional(
            CONF_MQTT_DISCOVERY_ENABLED,
            default=defaults.get(
                CONF_MQTT_DISCOVERY_ENABLED, DEFAULT_MQTT_DISCOVERY_ENABLED
            ),
        ): bool,
        vol.Optional(
            CONF_MQTT_DISCOVERY_PREFIX,
            default=defaults.get(
                CONF_MQTT_DISCOVERY_PREFIX, DEFAULT_MQTT_DISCOVERY_PREFIX
            ),
        ): str,
        vol.Optional(
            CONF_MQTT_HEARTBEAT_TIMEOUT,
            default=defaults.get(
                CONF_MQTT_HEARTBEAT_TIMEOUT, DEFAULT_MQTT_HEARTBEAT_TIMEOUT
            ),
        ): selector.NumberSelector(
            selector.NumberSelectorConfig(
                min=30,
                max=600,
                step=10,
                unit_of_measurement="s",
                mode=selector.NumberSelectorMode.BOX,
            )
        ),
        vol.Optional(
            CONF_WRITE_MODE,
            default=defaults.get(CONF_WRITE_MODE, WRITE_MODE_DEFAULT),
        ): vol.In(WRITE_MODES),
    }


def _options_from_user_input(user_input: dict[str, Any]) -> dict[str, Any]:
    """Baut das options-dict aus den Token-/MQTT-/Schreibpfad-Feldern eines Formulars."""
    return {
        CONF_API_TOKEN: user_input[CONF_API_TOKEN],
        CONF_MQTT_BASE_TOPIC: user_input[CONF_MQTT_BASE_TOPIC],
        CONF_MQTT_DISCOVERY_ENABLED: user_input[CONF_MQTT_DISCOVERY_ENABLED],
        CONF_MQTT_DISCOVERY_PREFIX: user_input[CONF_MQTT_DISCOVERY_PREFIX],
        CONF_MQTT_HEARTBEAT_TIMEOUT: user_input[CONF_MQTT_HEARTBEAT_TIMEOUT],
        CONF_WRITE_MODE: user_input[CONF_WRITE_MODE],
    }


class HaEmsEspConfigFlow(config_entries.ConfigFlow, domain=DOMAIN):
    """Config Flow fuer ha_ems_esp."""

    VERSION = 1

    _discovered_host: str

    async def async_step_user(
        self, user_input: dict[str, Any] | None = None
    ) -> FlowResult:
        """Erster (und einziger) Setup-Schritt: Host + MQTT-Grundeinstellungen."""
        errors: dict[str, str] = {}

        if user_input is not None:
            host = user_input[CONF_HOST]
            client = EmsEspApiClient(self.hass, host)
            try:
                system_info = await client.async_get_system_info()
            except CannotConnect:
                errors["base"] = "cannot_connect"
            else:
                unique_id = _build_unique_id(host, system_info)
                await self.async_set_unique_id(unique_id)
                self._abort_if_unique_id_configured()

                return self.async_create_entry(
                    title=f"EMS-ESP ({host})",
                    data={CONF_HOST: host},
                    options=_options_from_user_input(user_input),
                )

        schema = vol.Schema(
            {
                vol.Required(CONF_HOST): str,
                **_mqtt_schema(),
            }
        )
        return self.async_show_form(step_id="user", data_schema=schema, errors=errors)

    async def async_step_zeroconf(
        self, discovery_info: ZeroconfServiceInfo
    ) -> FlowResult:
        """Zeroconf hat einen Kandidaten gefunden (Name passt auf 'ems-esp*').

        Das reicht als Vor-Filter nicht aus (jedes HTTP-Geraet mit passendem
        Namen wuerde sonst durchrutschen) - wir validieren deshalb zusaetzlich
        per echtem /api/system/info Aufruf, bevor der Bestaetigungs-Dialog
        angezeigt wird.
        """
        host = discovery_info.host
        client = EmsEspApiClient(self.hass, host)
        try:
            system_info = await client.async_get_system_info()
        except CannotConnect:
            return self.async_abort(reason="cannot_connect")

        if "system" not in system_info or "mqtt" not in system_info:
            # Sieht aus wie ein HTTP-Geraet mit passendem mDNS-Namen, ist
            # aber vom Antwort-Schema her kein EMS-ESP - lieber abbrechen als
            # einen falschen Discovery-Vorschlag anzuzeigen.
            return self.async_abort(reason="not_ems_esp_device")

        unique_id = _build_unique_id(host, system_info)
        await self.async_set_unique_id(unique_id)
        self._abort_if_unique_id_configured(updates={CONF_HOST: host})

        self._discovered_host = host
        self.context["title_placeholders"] = {"host": host}
        return await self.async_step_zeroconf_confirm()

    async def async_step_zeroconf_confirm(
        self, user_input: dict[str, Any] | None = None
    ) -> FlowResult:
        """Bestaetigungs-Dialog fuer ein per Zeroconf gefundenes Gateway.

        Host ist bereits bekannt und validiert - hier werden nur noch die
        MQTT-/Schreibpfad-Einstellungen abgefragt, analog zu async_step_user.
        """
        if user_input is not None:
            return self.async_create_entry(
                title=f"EMS-ESP ({self._discovered_host})",
                data={CONF_HOST: self._discovered_host},
                options=_options_from_user_input(user_input),
            )

        schema = vol.Schema(_mqtt_schema())
        return self.async_show_form(
            step_id="zeroconf_confirm",
            data_schema=schema,
            description_placeholders={"host": self._discovered_host},
        )

    @staticmethod
    def async_get_options_flow(
        config_entry: config_entries.ConfigEntry,
    ) -> HaEmsEspOptionsFlow:
        """Options Flow fuer nachtraegliche MQTT-/Schreibpfad-Anpassungen."""
        return HaEmsEspOptionsFlow(config_entry)


class HaEmsEspOptionsFlow(config_entries.OptionsFlow):
    """Erlaubt das nachtraegliche Anpassen von MQTT-Einstellungen und Schreibpfad.

    Der REST-Host selbst wird hier bewusst nicht angeboten - eine Aenderung
    der Geraete-IP ist ein selteneres Ereignis und wuerde einen eigenen
    Reconfigure-Flow verdienen statt hier "nebenbei" mitzulaufen.
    """

    def __init__(self, config_entry: config_entries.ConfigEntry) -> None:
        self._config_entry = config_entry

    async def async_step_init(
        self, user_input: dict[str, Any] | None = None
    ) -> FlowResult:
        if user_input is not None:
            return self.async_create_entry(title="", data=user_input)

        schema = vol.Schema(_mqtt_schema(dict(self._config_entry.options)))
        return self.async_show_form(step_id="init", data_schema=schema)
