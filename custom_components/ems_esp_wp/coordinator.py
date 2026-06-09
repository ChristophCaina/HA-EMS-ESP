"""EMS-ESP coordinator — manages MQTT subscriptions and device state."""
from __future__ import annotations
import json
import logging
from typing import Any

from homeassistant.components import mqtt
from homeassistant.core import HomeAssistant, callback
from homeassistant.helpers.device_registry import DeviceInfo
from homeassistant.helpers.update_coordinator import DataUpdateCoordinator

from .const import (
    DOMAIN,
    DEVICE_GATEWAY,
    DEVICE_BOILER,
    DEVICE_DHW,
    DEVICE_THERMOSTAT,
    DEVICE_HC,
    TOPIC_STATUS,
    TOPIC_INFO,
    TOPIC_HEARTBEAT,
    TOPIC_BOILER_DATA,
    TOPIC_BOILER_DATA_WW,
    TOPIC_THERMOSTAT_DATA,
    TOPIC_TAPWATER_ACTIVE,
    TOPIC_HEATING_ACTIVE,
    PRODUCT_ID_NAMES,
)
from .models import (
    EmsEspGatewayInfo,
    EmsEspBoilerData,
    EmsEspDhwData,
    EmsEspHcData,
    EmsEspThermostatData,
)
from .parser import (
    parse_info,
    parse_heartbeat,
    parse_boiler_data,
    parse_boiler_data_with_dhw,
    parse_dhw_data,
    parse_thermostat_data,
)

_LOGGER = logging.getLogger(__name__)


def _resolve_device_name(product_id: int | None, fallback: str) -> str:
    """Return a friendly device name from product_id, or fallback."""
    if product_id and product_id in PRODUCT_ID_NAMES:
        return PRODUCT_ID_NAMES[product_id]
    if product_id:
        return f"EMS Device (ID {product_id})"
    return fallback


class EmsEspCoordinator(DataUpdateCoordinator):
    """
    Central coordinator for one EMS-ESP gateway instance.
    Manages MQTT subscriptions and notifies HA entities on data changes.
    """

    def __init__(
        self,
        hass: HomeAssistant,
        entry_id: str,
        base_topic: str,
        device_name: str,
    ) -> None:
        super().__init__(
            hass,
            _LOGGER,
            name=f"EMS-ESP {base_topic}",
        )
        self.entry_id = entry_id
        self.base_topic = base_topic
        self.configured_device_name = device_name

        # Data state
        self.gateway_info = EmsEspGatewayInfo()
        self.boiler_data: EmsEspBoilerData | None = None
        self.dhw_data: EmsEspDhwData | None = None
        self.thermostat_data: EmsEspThermostatData | None = None

        # MQTT unsubscribe callbacks
        self._unsub: list[Any] = []

    # ------------------------------------------------------------------
    # Device info helpers for HA device registry
    # ------------------------------------------------------------------

    def _base_device_info(self) -> dict:
        return {
            "identifiers": {(DOMAIN, self.entry_id)},
            "manufacturer": "EMS-ESP",
            "sw_version": self.gateway_info.version,
        }

    @property
    def gateway_device_info(self) -> DeviceInfo:
        return DeviceInfo(
            identifiers={(DOMAIN, f"{self.entry_id}_{DEVICE_GATEWAY}")},
            name=f"{self.configured_device_name} Gateway",
            manufacturer="BBQKees / EMS-ESP",
            model=f"EMS-ESP32 ({self.gateway_info.version})",
            sw_version=self.gateway_info.version,
            configuration_url=f"http://{self.gateway_info.hostname}.local",
        )

    @property
    def boiler_device_info(self) -> DeviceInfo:
        name = _resolve_device_name(
            self.boiler_data.product_id if self.boiler_data else None,
            self.configured_device_name,
        )
        return DeviceInfo(
            identifiers={(DOMAIN, f"{self.entry_id}_{DEVICE_BOILER}")},
            name=name,
            manufacturer="Bosch / Buderus",
            model=name,
            via_device=(DOMAIN, f"{self.entry_id}_{DEVICE_GATEWAY}"),
        )

    @property
    def dhw_device_info(self) -> DeviceInfo:
        boiler_name = _resolve_device_name(
            self.boiler_data.product_id if self.boiler_data else None,
            self.configured_device_name,
        )
        return DeviceInfo(
            identifiers={(DOMAIN, f"{self.entry_id}_{DEVICE_DHW}")},
            name=f"DHW / Warmwasser ({boiler_name})",
            manufacturer="Bosch / Buderus",
            via_device=(DOMAIN, f"{self.entry_id}_{DEVICE_GATEWAY}"),
        )

    def hc_device_info(self, hc_id: int) -> DeviceInfo:
        therm_name = _resolve_device_name(
            self.thermostat_data.product_id if self.thermostat_data else None,
            "Thermostat",
        )
        return DeviceInfo(
            identifiers={(DOMAIN, f"{self.entry_id}_{DEVICE_HC}{hc_id}")},
            name=f"{therm_name} HC{hc_id}",
            manufacturer="Bosch / Buderus",
            model=therm_name,
            via_device=(DOMAIN, f"{self.entry_id}_{DEVICE_GATEWAY}"),
        )

    # ------------------------------------------------------------------
    # MQTT subscription management
    # ------------------------------------------------------------------

    async def async_setup(self) -> None:
        """Subscribe to all relevant MQTT topics."""
        bt = self.base_topic

        topics = {
            TOPIC_STATUS: self._handle_status,
            TOPIC_INFO: self._handle_info,
            TOPIC_HEARTBEAT: self._handle_heartbeat,
            TOPIC_BOILER_DATA: self._handle_boiler_data,
            TOPIC_BOILER_DATA_WW: self._handle_boiler_data_ww,   # legacy v3.5
            TOPIC_THERMOSTAT_DATA: self._handle_thermostat_data,
            TOPIC_TAPWATER_ACTIVE: self._handle_tapwater_active,  # separate bool topic
            TOPIC_HEATING_ACTIVE: self._handle_heating_active,    # separate bool topic
        }

        for subtopic, handler in topics.items():
            full_topic = f"{bt}/{subtopic}"
            _LOGGER.debug("Subscribing to %s", full_topic)
            unsub = await mqtt.async_subscribe(
                self.hass,
                full_topic,
                handler,
                qos=0,
            )
            self._unsub.append(unsub)

    async def async_teardown(self) -> None:
        """Unsubscribe all MQTT topics."""
        for unsub in self._unsub:
            unsub()
        self._unsub.clear()

    # ------------------------------------------------------------------
    # MQTT message handlers
    # ------------------------------------------------------------------

    def _parse_json(self, payload: str) -> dict | None:
        try:
            return json.loads(payload)
        except (json.JSONDecodeError, TypeError) as e:
            _LOGGER.warning("Failed to parse JSON payload: %s — %s", payload[:80], e)
            return None

    @callback
    def _handle_status(self, msg: mqtt.ReceiveMessage) -> None:
        online = msg.payload.strip().lower() == "online"
        self.gateway_info.online = online
        _LOGGER.debug("Gateway %s status: %s", self.base_topic, msg.payload)
        self.async_set_updated_data(self._build_data_snapshot())

    @callback
    def _handle_info(self, msg: mqtt.ReceiveMessage) -> None:
        data = self._parse_json(msg.payload)
        if data is None:
            return
        self.gateway_info = parse_info(data)
        self.gateway_info.online = True
        _LOGGER.info(
            "EMS-ESP [%s] identified: version=%s hostname=%s",
            self.base_topic,
            self.gateway_info.version,
            self.gateway_info.hostname,
        )
        self.async_set_updated_data(self._build_data_snapshot())

    @callback
    def _handle_heartbeat(self, msg: mqtt.ReceiveMessage) -> None:
        data = self._parse_json(msg.payload)
        if data is None:
            return
        self.gateway_info = parse_heartbeat(data, self.gateway_info)
        self.async_set_updated_data(self._build_data_snapshot())

    @callback
    def _handle_tapwater_active(self, msg: mqtt.ReceiveMessage) -> None:
        """Handle separate tapwater_active topic (boolean string)."""
        val = msg.payload.strip().lower() in ("true", "on", "1", "yes")
        if self.dhw_data is None:
            from .models import EmsEspDhwData
            self.dhw_data = EmsEspDhwData()
        self.dhw_data.active = val
        self.gateway_info.online = True
        self.async_set_updated_data(self._build_data_snapshot())

    @callback
    def _handle_heating_active(self, msg: mqtt.ReceiveMessage) -> None:
        """Handle separate heating_active topic (boolean string)."""
        val = msg.payload.strip().lower() in ("true", "on", "1", "yes")
        if self.boiler_data is None:
            from .models import EmsEspBoilerData
            self.boiler_data = EmsEspBoilerData()
        self.boiler_data.heating_active = val
        self.gateway_info.online = True
        self.async_set_updated_data(self._build_data_snapshot())

    @callback
    def _handle_boiler_data(self, msg: mqtt.ReceiveMessage) -> None:
        data = self._parse_json(msg.payload)
        if data is None:
            return

        # Any valid data from EMS-ESP means gateway is online
        self.gateway_info.online = True

        boiler, dhw = parse_boiler_data_with_dhw(data)
        self.boiler_data = boiler

        # Only update DHW from nested data if we haven't already received
        # a dedicated boiler_data_ww topic (legacy support)
        if dhw is not None:
            self.dhw_data = dhw
            _LOGGER.debug("Updated DHW from nested boiler_data (v3.6+ style)")

        self.async_set_updated_data(self._build_data_snapshot())

    @callback
    def _handle_boiler_data_ww(self, msg: mqtt.ReceiveMessage) -> None:
        """Handle legacy boiler_data_ww topic (v3.5 and older / Simulator)."""
        data = self._parse_json(msg.payload)
        if data is None:
            return
        self.dhw_data = parse_dhw_data(data)
        _LOGGER.debug("Updated DHW from boiler_data_ww (legacy/simulator style)")
        self.async_set_updated_data(self._build_data_snapshot())

    @callback
    def _handle_thermostat_data(self, msg: mqtt.ReceiveMessage) -> None:
        data = self._parse_json(msg.payload)
        if data is None:
            return
        self.thermostat_data = parse_thermostat_data(data)
        self.async_set_updated_data(self._build_data_snapshot())

    # ------------------------------------------------------------------
    # Data snapshot (passed to all entities via coordinator.data)
    # ------------------------------------------------------------------

    def _build_data_snapshot(self) -> dict:
        return {
            "gateway": self.gateway_info,
            "boiler": self.boiler_data,
            "dhw": self.dhw_data,
            "thermostat": self.thermostat_data,
        }

    # ------------------------------------------------------------------
    # Command helpers (HA → EMS-ESP via MQTT)
    # ------------------------------------------------------------------

    async def async_publish_command(self, subtopic: str, payload: str) -> None:
        """Publish a command to EMS-ESP."""
        full_topic = f"{self.base_topic}/{subtopic}"
        _LOGGER.debug("Publishing command: %s = %s", full_topic, payload)
        await mqtt.async_publish(self.hass, full_topic, payload, qos=0, retain=False)

    async def _async_update_data(self) -> dict:
        """Called by DataUpdateCoordinator — we use push (MQTT), so just return current state."""
        return self._build_data_snapshot()
