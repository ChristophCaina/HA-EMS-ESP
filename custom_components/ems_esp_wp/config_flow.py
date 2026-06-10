"""Config flow for EMS-ESP Heat Pump integration."""
from __future__ import annotations
import logging
from typing import Any

import aiohttp
import voluptuous as vol

from homeassistant import config_entries
from homeassistant.components import mqtt
from homeassistant.data_entry_flow import FlowResult
from homeassistant.helpers.aiohttp_client import async_get_clientsession

from .const import (
    DOMAIN,
    CONF_BASE_TOPIC,
    CONF_DEVICE_NAME,
    CONF_EMS_ESP_IP,
    DEFAULT_BASE_TOPIC,
)

_LOGGER = logging.getLogger(__name__)


class EmsEspConfigFlow(config_entries.ConfigFlow, domain=DOMAIN):
    """Handle the config flow for EMS-ESP."""

    VERSION = 1

    async def async_step_user(
        self, user_input: dict[str, Any] | None = None
    ) -> FlowResult:
        errors: dict[str, str] = {}

        if not await mqtt.async_wait_for_mqtt_client(self.hass):
            return self.async_abort(reason="mqtt_not_configured")

        if user_input is not None:
            base_topic  = user_input[CONF_BASE_TOPIC].strip().strip("/")
            device_name = user_input.get(CONF_DEVICE_NAME, "").strip()
            ems_esp_ip  = user_input.get(CONF_EMS_ESP_IP, "").strip()

            await self.async_set_unique_id(base_topic)
            self._abort_if_unique_id_configured()

            # Try REST API if IP provided
            api_entities: dict = {}
            if ems_esp_ip:
                api_entities, device_name_api = await self._fetch_entities(ems_esp_ip)
                if api_entities is None:
                    errors[CONF_EMS_ESP_IP] = "cannot_connect"
                else:
                    if not device_name:
                        device_name = device_name_api

            if not errors:
                if not device_name:
                    device_name = f"EMS-ESP ({base_topic})"

                return self.async_create_entry(
                    title=device_name,
                    data={
                        CONF_BASE_TOPIC:  base_topic,
                        CONF_DEVICE_NAME: device_name,
                        CONF_EMS_ESP_IP:  ems_esp_ip,
                        "api_entities":   api_entities,
                    },
                )

        return self.async_show_form(
            step_id="user",
            data_schema=vol.Schema({
                vol.Required(CONF_BASE_TOPIC, default=DEFAULT_BASE_TOPIC): str,
                vol.Optional(CONF_EMS_ESP_IP, default=""): str,
                vol.Optional(CONF_DEVICE_NAME, default=""): str,
            }),
            errors=errors,
        )

    async def _fetch_entities(self, ip: str) -> tuple[dict | None, str]:
        """Fetch entity lists from EMS-ESP REST API."""
        session = async_get_clientsession(self.hass)
        entities: dict = {}
        device_name = ""

        for device_type in ("boiler", "thermostat", "heatpump", "mixer", "solar"):
            try:
                url = f"http://{ip}/api/{device_type}/entities"
                async with session.get(url, timeout=aiohttp.ClientTimeout(total=5)) as resp:
                    if resp.status == 200:
                        data = await resp.json(content_type=None)
                        if isinstance(data, list) and data:
                            entities[device_type] = data
                            _LOGGER.info(
                                "EMS-ESP API: %s has %d entities",
                                device_type, len(data)
                            )
            except Exception as e:
                _LOGGER.debug("EMS-ESP API %s/%s: %s", ip, device_type, e)

        # Try to get device name from info endpoint
        try:
            async with session.get(
                f"http://{ip}/api/system/info",
                timeout=aiohttp.ClientTimeout(total=5)
            ) as resp:
                if resp.status == 200:
                    info = await resp.json(content_type=None)
                    # Try to extract product name
                    if isinstance(info, dict):
                        device_name = info.get("productname") or info.get("hostname") or ""
        except Exception:
            pass

        if not entities:
            return None, ""
        return entities, device_name

    @staticmethod
    def async_get_options_flow(config_entry):
        return EmsEspOptionsFlow()


class EmsEspOptionsFlow(config_entries.OptionsFlow):
    """Handle options."""

    async def async_step_init(
        self, user_input: dict[str, Any] | None = None
    ) -> FlowResult:
        if user_input is not None:
            new_data = dict(self.config_entry.data)
            new_data[CONF_BASE_TOPIC]  = user_input.get(CONF_BASE_TOPIC, DEFAULT_BASE_TOPIC).strip().strip("/")
            new_data[CONF_DEVICE_NAME] = user_input.get(CONF_DEVICE_NAME, "")
            new_data[CONF_EMS_ESP_IP]  = user_input.get(CONF_EMS_ESP_IP, "").strip()
            self.hass.config_entries.async_update_entry(self.config_entry, data=new_data)
            return self.async_create_entry(title="", data={})

        return self.async_show_form(
            step_id="init",
            data_schema=vol.Schema({
                vol.Required(
                    CONF_BASE_TOPIC,
                    default=self.config_entry.data.get(CONF_BASE_TOPIC, DEFAULT_BASE_TOPIC),
                ): str,
                vol.Optional(
                    CONF_EMS_ESP_IP,
                    default=self.config_entry.data.get(CONF_EMS_ESP_IP, ""),
                ): str,
                vol.Optional(
                    CONF_DEVICE_NAME,
                    default=self.config_entry.data.get(CONF_DEVICE_NAME, ""),
                ): str,
            }),
        )
