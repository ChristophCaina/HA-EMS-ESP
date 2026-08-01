"""Zentrale IDs fuer Home Assistant Repair Issues.

An einer Stelle definiert, damit __init__.py (Setup-Zeit-Checks) und
mqtt.py (Laufzeit-Checks) garantiert dieselbe issue_id fuer denselben
Sachverhalt verwenden - sonst koennten zwei verschiedene Issues fuer das
gleiche Problem entstehen, oder eines wuerde nie wieder geloescht.
"""
from __future__ import annotations

from homeassistant.config_entries import ConfigEntry


def mqtt_unavailable_issue_id(entry: ConfigEntry) -> str:
    return f"mqtt_unavailable_{entry.entry_id}"


def gateway_unreachable_issue_id(entry: ConfigEntry) -> str:
    return f"gateway_unreachable_{entry.entry_id}"
