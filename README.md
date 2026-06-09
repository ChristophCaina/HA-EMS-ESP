# HA-EMS-ESP — Home Assistant Integration für EMS-ESP

[![HACS Custom](https://img.shields.io/badge/HACS-Custom-orange.svg)](https://github.com/hacs/integration)
[![Version](https://img.shields.io/badge/version-0.1.0-blue.svg)](https://github.com/ChristophCaina/HA-EMS-ESP/releases)

Custom Component für Home Assistant zur Integration von [EMS-ESP](https://emsesp.org) Gateways (BBQKees ESP32) mit Buderus / Bosch Wärmepumpen und Heizkesseln.

---

## Features

- **Multi-Instanz**: Mehrere EMS-ESP Gateways (unterschiedliche Base Topics) parallel betreiben
- **Multi-Version**: Unterstützt EMS-ESP v3.5 (legacy `boiler_data_ww`) und v3.6+ (DHW nested in `boiler_data`)
- **Automatische Geräteerkennung**: Modellname aus Product-ID (Buderus WLW186i-12, RC310, etc.)
- **Logische Geräteaufteilung**:
  - 🔧 EMS-ESP Gateway (Version, Uptime, Bus-Status)
  - 🔥 Wärmeerzeuger / Boiler (Temperaturen, COP, Leistung, Energie)
  - 💧 DHW / Warmwasser (Ist/Soll-Temperatur, Aktivierung)
  - 🏠 Heizkreis HC1..n (Solltemperatur, Betriebsart, Heizkurve)

### Unterstützte Entity-Typen

| Typ | Beispiele |
|---|---|
| `sensor` | Vorlauf, Rücklauf, Außentemp, COP, Leistung, Energie, Uptime |
| `binary_sensor` | Heizung aktiv, Kompressor aktiv, Warmwasser aktiv |
| `number` | WW Solltemperatur, VL Max/Min, Heizkurve Neigung, Max-Leistung |
| `select` | PV-Modus, Silent-Modus, HC Betriebsart |
| `switch` | Warmwasser aktiviert |
| `button` | Manuelles Abtauen |
| `climate` | Heizkreis HC1 als vollständige Climate-Entity |

---

## Installation

### Via HACS (empfohlen)

1. HACS → Integrationen → ⋮ → Benutzerdefinierte Repositories
2. URL: `https://github.com/ChristophCaina/HA-EMS-ESP` — Kategorie: Integration
3. Integration "EMS-ESP Heat Pump" installieren
4. HA neu starten

### Manuell

```bash
cp -r custom_components/ems_esp_wp /config/custom_components/
```
HA neu starten.

---

## Einrichtung

1. Einstellungen → Integrationen → Integration hinzufügen → **EMS-ESP**
2. MQTT Base Topic eingeben (Standard: `ems-esp`)
3. Optional: Gerätename (wird sonst automatisch aus Product-ID erkannt)

Für ein zweites EMS-ESP Gateway: Integration erneut hinzufügen mit anderem Base Topic (z.B. `ems-esp2`).

---

## MQTT Topics

Die Integration subscribt folgende Topics (relativ zum Base Topic):

| Topic | Beschreibung |
|---|---|
| `{base}/status` | Online/Offline (LWT) |
| `{base}/info` | Version, Hostname |
| `{base}/heartbeat` | Uptime, Bus-Status |
| `{base}/boiler_data` | Heizdaten + optional DHW nested (v3.6+) |
| `{base}/boiler_data_ww` | DHW Daten (legacy v3.5 / Simulator) |
| `{base}/thermostat_data` | Heizkreise HC1..n |

Commands werden publiziert nach `{base}/boiler/<entity>` bzw. `{base}/thermostat/hc1/<entity>`.

---

## Entwicklungsstand

| Phase | Status |
|---|---|
| v0.1.0 — Basis-Integration (Simulator / v3.5) | ✅ In Arbeit |
| v0.2.0 — Zweite Instanz, v3.6+ DHW nested Test | 🔜 Geplant |
| v0.3.0 — Dynamische HC-Entities (HC2..4) | 🔜 Geplant |
| v1.0.0 — HACS-Release | 🔜 Geplant |

---

## Verwandtes Projekt

Simulator für Entwicklung & Tests ohne echte Hardware:
👉 [EMS-ESP-WP-Simulator](https://github.com/ChristophCaina/EMS-ESP-WP-Simulator)
