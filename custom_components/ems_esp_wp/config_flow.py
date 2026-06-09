"""Config flow for EMS-ESP Heat Pump integration."""
from __future__ import annotations
import logging
from typing import Any

import voluptuous as vol

from homeassistant import config_entries
from homeassistant.components import mqtt
from homeassistant.data_entry_flow import FlowResult

from .const import (
    DOMAIN,
    CONF_BASE_TOPIC,
    CONF_DEVICE_NAME,
    DEFAULT_BASE_TOPIC,
)

_LOGGER = logging.getLogger(__name__)

STEP_USER_SCHEMA = vol.Schema(
    {
        vol.Required(CONF_BASE_TOPIC, default=DEFAULT_BASE_TOPIC): str,
        vol.Optional(CONF_DEVICE_NAME, default=""): str,
    }
)


class EmsEspConfigFlow(config_entries.ConfigFlow, domain=DOMAIN):
    """Handle the config flow for EMS-ESP."""

    VERSION = 1

    async def async_step_user(
        self, user_input: dict[str, Any] | None = None
    ) -> FlowResult:
        errors: dict[str, str] = {}

        # Check MQTT integration is available
        if not await mqtt.async_wait_for_mqtt_client(self.hass):
            return self.async_abort(reason="mqtt_not_configured")

        if user_input is not None:
            base_topic = user_input[CONF_BASE_TOPIC].strip().strip("/")
            device_name = user_input.get(CONF_DEVICE_NAME, "").strip()

            # Prevent duplicate entries with the same base topic
            await self.async_set_unique_id(base_topic)
            self._abort_if_unique_id_configured()

            # Use base_topic as device name fallback
            if not device_name:
                device_name = f"EMS-ESP ({base_topic})"

            return self.async_create_entry(
                title=device_name,
                data={
                    CONF_BASE_TOPIC: base_topic,
                    CONF_DEVICE_NAME: device_name,
                },
            )

        return self.async_show_form(
            step_id="user",
            data_schema=STEP_USER_SCHEMA,
            errors=errors,
            description_placeholders={
                "mqtt_info": "Requires the MQTT integration to be configured.",
            },
        )

    @staticmethod
    def async_get_options_flow(config_entry):
        return EmsEspOptionsFlow()


class EmsEspOptionsFlow(config_entries.OptionsFlow):
    """Handle options (allow renaming device after setup)."""

    async def async_step_init(
        self, user_input: dict[str, Any] | None = None
    ) -> FlowResult:
        if user_input is not None:
            new_data = dict(self.config_entry.data)
            new_data[CONF_BASE_TOPIC] = user_input.get(CONF_BASE_TOPIC, DEFAULT_BASE_TOPIC).strip().strip("/")
            new_data[CONF_DEVICE_NAME] = user_input.get(CONF_DEVICE_NAME, "")
            self.hass.config_entries.async_update_entry(
                self.config_entry, data=new_data
            )
            return self.async_create_entry(title="", data={})

        return self.async_show_form(
            step_id="init",
            data_schema=vol.Schema(
                {
                    vol.Required(
                        CONF_BASE_TOPIC,
                        default=self.config_entry.data.get(CONF_BASE_TOPIC, DEFAULT_BASE_TOPIC),
                    ): str,
                    vol.Optional(
                        CONF_DEVICE_NAME,
                        default=self.config_entry.data.get(CONF_DEVICE_NAME, ""),
                    ): str,
                }
            ),
        )
