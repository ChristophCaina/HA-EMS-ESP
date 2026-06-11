"""Climate entity for EMS-ESP heating circuits."""
from __future__ import annotations
from homeassistant.components.climate import (
    ClimateEntity,
    ClimateEntityFeature,
    HVACMode,
    PRESET_NONE,
)
from homeassistant.config_entries import ConfigEntry
from homeassistant.const import UnitOfTemperature
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.helpers.update_coordinator import CoordinatorEntity

from .const import DOMAIN, DEVICE_HC

# ── HVAC mode mapping ─────────────────────────────────────────────────────────
# HA only has AUTO / HEAT / COOL / OFF as standard HVAC modes.
# EMS-ESP granular modes (day/night/eco/manual) are exposed via preset_mode.
#
# HVAC mode logic:
#   AUTO  → EMS "auto"    (Zeitplan-gesteuert, Tag/Nacht-Automatik)
#   HEAT  → EMS "day"     (Heizbetrieb aktiv, Preset verfeinert)
#   OFF   → EMS "nofrost" (Frostschutz)
#
# Preset logic (only active when HVAC = HEAT or AUTO):
#   "day"     → EMS "day"     (Tagbetrieb)
#   "night"   → EMS "night"   (Nachtbetrieb/abgesenkt)
#   "eco"     → EMS "eco"     (Energiesparmodus)
#   "manual"  → EMS "manual"  (Manueller Vorlauf)
#   "auto"    → EMS "auto"    (Zeitplan-Automatik)
#   none      → keine Änderung

EMS_TO_HA_HVAC: dict[str, HVACMode] = {
    "auto":    HVACMode.AUTO,
    "day":     HVACMode.HEAT,
    "manual":  HVACMode.HEAT,
    "comfort": HVACMode.HEAT,
    "night":   HVACMode.HEAT,   # night = reduced heat, not cooling
    "eco":     HVACMode.HEAT,   # eco = energy-saving heat
    "cooling": HVACMode.COOL,   # only reachable if device supports cooling
    "nofrost": HVACMode.OFF,
    "off":     HVACMode.OFF,
    "holiday": HVACMode.OFF,
}

# EMS mode → preset label (for display in HA)
EMS_TO_PRESET: dict[str, str] = {
    "auto":    "auto",
    "day":     "day",
    "night":   "night",
    "eco":     "eco",
    "manual":  "manual",
    "comfort": "day",     # treat comfort as day
    "nofrost": PRESET_NONE,
    "off":     PRESET_NONE,
    "holiday": PRESET_NONE,
}

# Preset label → EMS mode (for set_preset_mode)
PRESET_TO_EMS: dict[str, str] = {
    "auto":   "auto",
    "day":    "day",
    "night":  "night",
    "eco":    "eco",
    "manual": "manual",
}

# All available presets
ALL_PRESETS = ["auto", "day", "night", "eco", "manual"]


async def async_setup_entry(
    hass: HomeAssistant,
    entry: ConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    coordinator = hass.data[DOMAIN][entry.entry_id]
    async_add_entities([EmsEspClimate(coordinator, hc_id=1)])


class EmsEspClimate(CoordinatorEntity, ClimateEntity):
    """Climate entity representing one heating circuit.

    HVAC modes:   AUTO (Zeitplan), HEAT (aktiv heizen), OFF (Frostschutz)
    Preset modes: auto / day / night / eco / manual
    """

    _attr_temperature_unit = UnitOfTemperature.CELSIUS
    _attr_supported_features = (
        ClimateEntityFeature.TARGET_TEMPERATURE
        | ClimateEntityFeature.PRESET_MODE
    )
    # hvac_modes and preset_modes are dynamic (device-dependent), defined as properties below
    _attr_min_temp = 5.0
    _attr_max_temp = 30.0
    _attr_target_temperature_step = 0.5
    _attr_has_entity_name = True
    _attr_translation_key = "heizkreis"

    def __init__(self, coordinator, hc_id: int) -> None:
        super().__init__(coordinator)
        self._hc_id = hc_id
        self._attr_unique_id = f"{coordinator.entry_id}_climate_hc{hc_id}"
        self._attr_name = f"Heizkreis HC{hc_id}"

    @property
    def device_info(self):
        return self.coordinator.hc_device_info(self._hc_id)

    def _get_hc(self):
        if self.coordinator.data and self.coordinator.data["thermostat"]:
            return self.coordinator.data["thermostat"].hcs.get(self._hc_id)
        return None

    def _ems_mode(self) -> str:
        hc = self._get_hc()
        return hc.mode.lower() if hc and hc.mode else "auto"

    @property
    def current_temperature(self) -> float | None:
        hc = self._get_hc()
        return hc.cur_temp if hc else None

    @property
    def target_temperature(self) -> float | None:
        hc = self._get_hc()
        return hc.sel_temp if hc else None

    @property
    def hvac_modes(self) -> list[HVACMode]:
        """Dynamic: include COOL only if device reports cooling support."""
        modes = [HVACMode.AUTO, HVACMode.HEAT, HVACMode.OFF]
        hc = self._get_hc()
        if hc and "cooling" in (hc.supported_modes or []):
            modes.insert(2, HVACMode.COOL)
        return modes

    @property
    def preset_modes(self) -> list[str]:
        """Dynamic: only presets the device actually supports."""
        hc = self._get_hc()
        if not hc or not hc.supported_modes:
            return ALL_PRESETS  # fallback to full list
        # Map EMS modes to preset labels, keep only what device reports
        return [m for m in ALL_PRESETS if PRESET_TO_EMS.get(m) in hc.supported_modes]

    @property
    def hvac_mode(self) -> HVACMode:
        return EMS_TO_HA_HVAC.get(self._ems_mode(), HVACMode.AUTO)

    @property
    def preset_mode(self) -> str | None:
        return EMS_TO_PRESET.get(self._ems_mode(), PRESET_NONE)

    async def async_set_temperature(self, **kwargs) -> None:
        temp = kwargs.get("temperature")
        if temp is not None:
            await self.coordinator.async_publish_command(
                f"thermostat/hc{self._hc_id}/seltemp", str(temp)
            )

    async def async_set_hvac_mode(self, hvac_mode: HVACMode) -> None:
        """Map HA HVAC mode to EMS mode.

        AUTO → "auto", HEAT → "day" (Tagbetrieb als sinnvoller Default),
        OFF  → "nofrost"
        """
        ems_mode = {
            HVACMode.AUTO: "auto",
            HVACMode.HEAT: "day",
            HVACMode.COOL: "cooling",
            HVACMode.OFF:  "nofrost",
        }.get(hvac_mode, "auto")
        await self.coordinator.async_publish_command(
            f"thermostat/hc{self._hc_id}/mode", ems_mode
        )

    async def async_set_preset_mode(self, preset_mode: str) -> None:
        """Set granular EMS mode via preset.

        Preset directly maps to EMS mode, so day/night/eco/manual/auto
        all send the exact EMS string to the thermostat.
        """
        ems_mode = PRESET_TO_EMS.get(preset_mode)
        if ems_mode:
            await self.coordinator.async_publish_command(
                f"thermostat/hc{self._hc_id}/mode", ems_mode
            )

    @property
    def available(self) -> bool:
        return self.coordinator.gateway_info.online


# ── PARSER NOTE ──────────────────────────────────────────────────────────────
# In parser.py → parse_thermostat_data(), when building EmsEspHcData,
# read the "mode" field's enum list from the API entities:
#
#   hc.supported_modes = api_entity.get("enum", [])
#
# The EMS-ESP API returns something like:
#   {"name": "mode", "type": "enum", "writeable": true,
#    "value": "day",
#    "enum": ["auto", "manual", "day", "night", "eco", "nofrost"]}
#
# For a device with cooling support it would include "cooling" in that list.
# If the API doesn't provide enum info, supported_modes stays [] and
# climate.py falls back to ALL_PRESETS (safe default).
