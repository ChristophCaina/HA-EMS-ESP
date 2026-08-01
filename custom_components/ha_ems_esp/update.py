"""Update-Plattform fuer ha_ems_esp.

Rein informativ: zeigt installierte vs. neueste verfuegbare EMS-ESP32
Firmware-Version (aus GitHub Releases, siehe coordinator.py), verlinkt auf
die Release Notes.

BEWUSST KEIN automatisches Flashen (UpdateEntityFeature.INSTALL): GitHub-
Releases enthalten mehrere .bin-Varianten pro Board-Profil (ESP32/
ESP32-S3/ESP32-C3/...), ein falsch zugeordnetes Binary kann das Geraet
unbrauchbar machen ("bricken") - im esp8266-react-Framework-Issue-Tracker
(dem Web-UI-Unterbau von EMS-ESP) explizit als reales Risiko dokumentiert.
Der exakte Upload-Endpunkt und das erforderliche Matching zum Board-Profil
sind nicht mit ausreichender Sicherheit verifiziert, um das automatisiert
und unbeaufsichtigt auszuloesen. Update bleibt manuell ueber das EMS-ESP
Webinterface (Settings -> Firmware Update).
"""
from __future__ import annotations

from homeassistant.components.update import UpdateDeviceClass, UpdateEntity
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity import DeviceInfo
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.helpers.update_coordinator import CoordinatorEntity

from .const import DOMAIN
from .coordinator import EmsEspFirmwareCoordinator, EmsEspSystemCoordinator

_RELEASE_SUMMARY_MAX_LENGTH = 255


async def async_setup_entry(
    hass: HomeAssistant, entry: ConfigEntry, async_add_entities: AddEntitiesCallback
) -> None:
    data = hass.data[DOMAIN][entry.entry_id]
    async_add_entities(
        [
            EmsEspFirmwareUpdate(
                data["firmware_coordinator"], data["system_coordinator"], entry
            )
        ]
    )


class EmsEspFirmwareUpdate(CoordinatorEntity[EmsEspFirmwareCoordinator], UpdateEntity):
    """Zeigt installierte vs. neueste EMS-ESP32-Firmware-Version."""

    _attr_has_entity_name = True
    _attr_name = "Firmware"
    _attr_device_class = UpdateDeviceClass.FIRMWARE

    def __init__(
        self,
        coordinator: EmsEspFirmwareCoordinator,
        system_coordinator: EmsEspSystemCoordinator,
        entry: ConfigEntry,
    ) -> None:
        super().__init__(coordinator)
        self._system_coordinator = system_coordinator
        self._attr_unique_id = f"{entry.unique_id or entry.entry_id}_firmware_update"
        self._attr_device_info = DeviceInfo(
            identifiers={(DOMAIN, entry.unique_id or entry.entry_id)}
        )

    @property
    def installed_version(self) -> str | None:
        return (self._system_coordinator.data or {}).get("system", {}).get("version")

    @property
    def latest_version(self) -> str | None:
        release = self.coordinator.data
        if not release:
            # Kein GitHub-Ergebnis (Rate-Limit, Netzwerkfehler, kein
            # "latest"-Release) - als "aktuell" zeigen statt faelschlich
            # ein Update zu suggerieren.
            return self.installed_version
        tag = release.get("tag_name", "")
        return tag.lstrip("vV") or self.installed_version

    @property
    def release_url(self) -> str | None:
        release = self.coordinator.data
        return release.get("html_url") if release else None

    @property
    def release_summary(self) -> str | None:
        release = self.coordinator.data
        if not release:
            return None
        body = (release.get("body") or "").strip()
        if not body:
            return None
        if len(body) > _RELEASE_SUMMARY_MAX_LENGTH:
            return body[: _RELEASE_SUMMARY_MAX_LENGTH - 1] + "…"
        return body
