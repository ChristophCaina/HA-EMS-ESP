"""EMS-ESP Heat Pump — Custom Integration for Home Assistant."""
from __future__ import annotations
import logging

from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant

from .const import DOMAIN, CONF_BASE_TOPIC, CONF_DEVICE_NAME
from .coordinator import EmsEspCoordinator

_LOGGER = logging.getLogger(__name__)

PLATFORMS = ["sensor", "binary_sensor", "number", "select", "switch", "button", "climate"]


async def async_setup_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    """Set up EMS-ESP from a config entry."""
    base_topic = entry.data[CONF_BASE_TOPIC]
    device_name = entry.data.get(CONF_DEVICE_NAME, f"EMS-ESP ({base_topic})")

    coordinator = EmsEspCoordinator(
        hass=hass,
        entry_id=entry.entry_id,
        base_topic=base_topic,
        device_name=device_name,
    )

    # Start MQTT subscriptions
    await coordinator.async_setup()

    # Store coordinator for platform access
    hass.data.setdefault(DOMAIN, {})[entry.entry_id] = coordinator

    # Forward to platforms
    await hass.config_entries.async_forward_entry_setups(entry, PLATFORMS)

    # Register options update listener
    entry.async_on_unload(entry.add_update_listener(async_reload_entry))

    _LOGGER.info("EMS-ESP integration set up for base topic: %s", base_topic)
    return True


async def async_unload_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    """Unload a config entry."""
    if unload_ok := await hass.config_entries.async_unload_platforms(entry, PLATFORMS):
        coordinator: EmsEspCoordinator = hass.data[DOMAIN].pop(entry.entry_id)
        await coordinator.async_teardown()
    return unload_ok


async def async_reload_entry(hass: HomeAssistant, entry: ConfigEntry) -> None:
    """Reload entry when options change."""
    await async_unload_entry(hass, entry)
    await async_setup_entry(hass, entry)
