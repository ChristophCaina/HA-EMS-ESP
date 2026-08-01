"""Statische Beschreibung schreibbarer Gateway-Einstellungen.

Kommen aus /api/system/info -> "settings" (z.B. showerTimer, showerAlert) -
NICHT aus der dynamischen entity_factory.py-Pipeline. Die ist an
structure_coordinator/devices[] gebunden; Gateway-Settings sind aber Teil
des Gateways selbst, kein eigener EMS-Bus-Geraetetyp. Analog zum Muster in
gateway_diagnostics.py, nur zusaetzlich schreibbar.

SCHREIBPFAD: POST /api/system/<circuit>/<name> (z.B.
/api/system/settings/showerTimer) - BESTAETIGT gegen echte Tests fuer
circuit="settings" (showerTimer, showerAlert). Anderer URL-Aufbau als der
normale Geraete-Schreibpfad (/api/<device>/<command>) - siehe
api.py:async_post_system_setting.
"""
from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from typing import Any

from homeassistant.const import EntityCategory


@dataclass(frozen=True, kw_only=True)
class GatewaySwitchDescription:
    key: str  # API name innerhalb des Circuits, z.B. "showerTimer"
    circuit: str  # z.B. "settings" - siehe api.py:async_post_system_setting
    name: str
    value_fn: Callable[[dict[str, Any]], Any]
    icon: str | None = None
    entity_category: EntityCategory | None = EntityCategory.CONFIG


GATEWAY_SWITCHES: tuple[GatewaySwitchDescription, ...] = (
    GatewaySwitchDescription(
        key="showerTimer",
        circuit="settings",
        name="Duschtimer",
        icon="mdi:shower-head",
        value_fn=lambda info: info.get("settings", {}).get("showerTimer"),
    ),
    GatewaySwitchDescription(
        key="showerAlert",
        circuit="settings",
        name="Duschalarm",
        icon="mdi:alarm-light-outline",
        value_fn=lambda info: info.get("settings", {}).get("showerAlert"),
    ),
)
