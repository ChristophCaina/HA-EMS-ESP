"""Version-aware MQTT payload parsers for EMS-ESP."""
from __future__ import annotations
import logging
from typing import Any

from .models import (
    EmsEspGatewayInfo,
    EmsEspBoilerData,
    EmsEspDhwData,
    EmsEspHcData,
    EmsEspThermostatData,
)

_LOGGER = logging.getLogger(__name__)


def _safe_float(data: dict, key: str) -> float | None:
    val = data.get(key)
    if val is None:
        return None
    try:
        return float(val)
    except (ValueError, TypeError):
        return None


def _safe_int(data: dict, key: str) -> int | None:
    val = data.get(key)
    if val is None:
        return None
    try:
        return int(val)
    except (ValueError, TypeError):
        return None


def _safe_bool(data: dict, key: str) -> bool:
    val = data.get(key)
    if isinstance(val, bool):
        return val
    if isinstance(val, str):
        return val.lower() in ("on", "true", "1", "yes", "active")
    if isinstance(val, (int, float)):
        return bool(val)
    return False


def _parse_uptime_to_seconds(uptime_str: str) -> int:
    """
    Parse EMS-ESP uptime string to total seconds.
    Formats seen:
      '000+00:34:10'  → days+HH:MM:SS
      '0 days 00:34:10'
      '02:16:00'       → HH:MM:SS only
      '3720'           → already seconds
    """
    if not uptime_str:
        return 0
    s = str(uptime_str).strip()
    # Try plain integer (seconds)
    try:
        return int(s)
    except ValueError:
        pass
    # Format: DDD+HH:MM:SS or DDD days HH:MM:SS
    import re
    m = re.match(r"(\d+)[+\s](?:days?\s*)?(\d+):(\d+):(\d+)", s)
    if m:
        days, hours, mins, secs = int(m.group(1)), int(m.group(2)), int(m.group(3)), int(m.group(4))
        return days * 86400 + hours * 3600 + mins * 60 + secs
    # Format: HH:MM:SS
    m = re.match(r"(\d+):(\d+):(\d+)", s)
    if m:
        hours, mins, secs = int(m.group(1)), int(m.group(2)), int(m.group(3))
        return hours * 3600 + mins * 60 + secs
    return 0


def _format_uptime(uptime_str: str) -> str:
    """Return a human-readable uptime string like '2d 03:15:42'."""
    total = _parse_uptime_to_seconds(uptime_str)
    days = total // 86400
    remainder = total % 86400
    hours = remainder // 3600
    mins = (remainder % 3600) // 60
    secs = remainder % 60
    if days > 0:
        return f"{days}d {hours:02d}:{mins:02d}:{secs:02d}"
    return f"{hours:02d}:{mins:02d}:{secs:02d}"


def parse_info(payload: dict) -> EmsEspGatewayInfo:
    """Parse the info topic payload."""
    info = EmsEspGatewayInfo(
        version=payload.get("version", "unknown"),
        hostname=payload.get("hostname", "ems-esp"),
        online=True,
    )
    info.parse_version()
    return info


def parse_heartbeat(payload: dict, existing: EmsEspGatewayInfo) -> EmsEspGatewayInfo:
    """Update gateway info from heartbeat payload."""
    existing.bus_status = payload.get("bus_status", payload.get("busstatus", "unknown"))
    raw_uptime = payload.get("uptime", "0")
    existing.uptime = _format_uptime(raw_uptime)
    existing.uptime_seconds = _parse_uptime_to_seconds(raw_uptime)
    existing.wifi_rssi = _safe_int(payload, "rssi") or _safe_int(payload, "rssid") or 0
    existing.free_mem = _safe_int(payload, "freemem") or 0
    existing.mqtt_fails = _safe_int(payload, "mqttpublishfails") or 0
    # Some EMS-ESP versions include version in heartbeat — use as fallback
    if "version" in payload and existing.version in ("unknown", "", None):
        existing.version = payload["version"]
        existing.parse_version()
    existing.online = True
    return existing


def parse_boiler_data(payload: dict) -> EmsEspBoilerData:
    """Parse boiler_data topic (heating side only)."""
    data = EmsEspBoilerData(raw=payload)

    # Temperatures
    data.cur_flow_temp = _safe_float(payload, "curflowtemp")
    data.ret_temp = _safe_float(payload, "rettemp")
    data.outside_temp = _safe_float(payload, "outdoortemp") or _safe_float(payload, "outdoorTemp")
    data.heat_exchanger_temp = _safe_float(payload, "heatexchangertemp")

    # State
    data.heating_active = _safe_bool(payload, "heatingactive")
    data.service_code = payload.get("servicecode") or payload.get("serviceCode")
    data.service_code_number = _safe_int(payload, "servicecodenumber")

    # Heat pump
    data.hp_compressor_on = _safe_bool(payload, "hpcompon")
    data.hp_circ_pump_on = _safe_bool(payload, "hpcircpump")
    data.hp_activity = payload.get("hpactivity")
    data.hp_cop = _safe_float(payload, "hpcop") or _safe_float(payload, "cop")  # simulator: "cop"
    data.hp_power_input = (
        _safe_float(payload, "hppowerinput")
        or _safe_float(payload, "powerinput")
        or _safe_float(payload, "hpcurrpower")  # simulator key (W electrical)
    )
    # hppower: real EMS-ESP sends kW thermal (firmware 12.11.1+), stored as-is (kW)
    data.hp_power_output = _safe_float(payload, "hppower")

    # Settings
    data.hp_max_power = _safe_int(payload, "hpmaxpower")
    data.silent_mode = _safe_int(payload, "silentmode")
    data.pv_mode = payload.get("pvmode")

    # Refrigerant circuit temperatures
    data.hp_tc0 = _safe_float(payload, "hptc0")
    data.hp_tc1 = _safe_float(payload, "hptc1")
    data.hp_tc3 = _safe_float(payload, "hptc3")
    data.hp_tr1 = _safe_float(payload, "hptr1")
    data.hp_tr3 = _safe_float(payload, "hptr3")
    data.hp_tr4 = _safe_float(payload, "hptr4")
    data.hp_tr5 = _safe_float(payload, "hptr5")
    data.hp_tr6 = _safe_float(payload, "hptr6")
    data.hp_tl2 = _safe_float(payload, "hptl2")
    data.hp_pl1 = _safe_float(payload, "hppl1")
    data.hp_ph1 = _safe_float(payload, "hpph1")
    data.hp_ta4 = _safe_float(payload, "hpta4")

    # Flow temps
    data.sel_flow_temp = _safe_float(payload, "selflowtemp")

    # Pumps
    data.heating_pump = _safe_bool(payload, "heatingpump")
    data.heating_pump_mod = _safe_int(payload, "heatingpumpmod") or _safe_int(payload, "pumpmod")
    data.hp_circ_spd = _safe_int(payload, "hpcircspd")
    data.hp_compressor_spd = _safe_int(payload, "hpcompspd") or _safe_int(payload, "curburnpow")

    # Activity
    data.hp_activity = payload.get("hpactivity")

    # Energy — precise (meter* preferred, nrg* fallback)
    data.nrg_total    = _safe_float(payload, "nrgtotal")
    data.nrg_heat     = _safe_float(payload, "nrgheat")
    data.nrg_cool     = _safe_float(payload, "nrgcool")
    data.meter_total  = _safe_float(payload, "metertotal")
    data.meter_comp   = _safe_float(payload, "metercomp")
    data.meter_eheat  = _safe_float(payload, "metereheat")
    data.meter_heat   = _safe_float(payload, "meterheat")
    data.meter_cool   = _safe_float(payload, "metercool")

    # Energy — legacy integer kWh
    data.nrg_cons_total              = _safe_float(payload, "nrgconstotal")
    data.nrg_cons_comp_total         = _safe_float(payload, "nrgconscomptotal")
    data.nrg_cons_comp_heating       = _safe_float(payload, "nrgconscompheating")
    data.aux_elec_heat_nrg_cons_total = _safe_float(payload, "auxelecheatnrgconstotal")

    # Statistics
    data.burn_starts   = _safe_int(payload, "burnstarts")
    data.burn_work_min = _safe_int(payload, "burnworkmin")

    # Product ID (v3.4+)
    data.product_id = _safe_int(payload, "id") or _safe_int(payload, "product_id")

    return data


def parse_dhw_data(payload: dict) -> EmsEspDhwData:
    """Parse DHW data — works for both boiler_data_ww (legacy) and nested dhw{} dict."""
    data = EmsEspDhwData(raw=payload)

    data.cur_temp = _safe_float(payload, "curtemp") or _safe_float(payload, "wwcurtemp") or _safe_float(payload, "wwstoragetemp")
    data.set_temp = (
        _safe_float(payload, "seltemp")
        or _safe_float(payload, "wwseltemp")
        or _safe_float(payload, "wwselectedtemp")
    )
    data.active = (
        _safe_bool(payload, "tapwateractive")  # simulator + real EMS-ESP
        or _safe_bool(payload, "active")
    )
    data.activated = (
        _safe_bool(payload, "wwactivated")   # simulator + legacy key
        if "wwactivated" in payload
        else _safe_bool(payload, "activated") if "activated" in payload
        else True
    )
    data.comfort = payload.get("comfort") or payload.get("wwcomfort")
    # Temperatures — accept both prefixed (ww*) and unprefixed keys
    data.cur_temp2 = _safe_float(payload, "curtemp2") or _safe_float(payload, "wwcurtemp2")
    # set_temp: real EMS-ESP uses "settemp", simulator uses "wwseltemp"
    if data.set_temp is None:
        data.set_temp = _safe_float(payload, "settemp") or _safe_float(payload, "wwseltemp")
    # Energy — precise
    data.nrg       = _safe_float(payload, "nrg")
    data.meter     = _safe_float(payload, "meter")
    data.nrg_comp  = _safe_float(payload, "nrgconscomp")
    data.aux_elec  = _safe_float(payload, "auxelecheatnrgcons")
    # Legacy
    data.nrg_total = _safe_float(payload, "nrgtotal") or _safe_float(payload, "wwnrgtotal") or _safe_float(payload, "nrg")
    data.product_id = _safe_int(payload, "id")

    return data


def parse_boiler_data_with_dhw(payload: dict) -> tuple[EmsEspBoilerData, EmsEspDhwData | None]:
    """
    Parse boiler_data payload that may contain nested dhw{} (v3.6+).
    Returns (boiler_data, dhw_data_or_None).
    """
    boiler = parse_boiler_data(payload)
    dhw = None

    # Check for nested DHW data (v3.6+ style)
    dhw_payload = payload.get("dhw") or payload.get("ww")
    if dhw_payload and isinstance(dhw_payload, dict):
        dhw = parse_dhw_data(dhw_payload)
        _LOGGER.debug("Parsed nested DHW data from boiler_data")

    return boiler, dhw


def parse_thermostat_data(payload: dict) -> EmsEspThermostatData:
    """
    Parse thermostat_data payload (nested format with hc1..hcN).
    Also handles flat payload (single HC, legacy).
    """
    therm = EmsEspThermostatData(raw=payload)
    therm.product_id = _safe_int(payload, "id")
    therm.target_flow_temp = _safe_float(payload, "targetflowtemp") or _safe_float(payload, "flowtarget")

    # Root-level fields that apply to all HCs (simulator puts dampedoutdoortemp here)
    root_dampedtemp = _safe_float(payload, "dampedoutdoortemp")

    # Try nested HCs first (standard v3 nested format)
    found_hc = False
    for i in range(1, 5):
        key = f"hc{i}"
        if key in payload and isinstance(payload[key], dict):
            therm.hcs[i] = _parse_hc(payload[key], i)
            # Inject root-level dampedoutdoortemp if HC doesn't have its own
            if root_dampedtemp is not None and therm.hcs[i].damped_outdoor_temp is None:
                therm.hcs[i].damped_outdoor_temp = root_dampedtemp
            found_hc = True

    # Fallback: flat payload treated as HC1 (some legacy modes / single-value topics)
    if not found_hc and ("seltemp" in payload or "mode" in payload):
        therm.hcs[1] = _parse_hc(payload, 1)

    return therm


def _parse_hc(payload: dict, hc_id: int) -> EmsEspHcData:
    """Parse a single heating circuit dict."""
    hc = EmsEspHcData(hc_id=hc_id, raw=payload)
    hc.sel_temp = _safe_float(payload, "seltemp")
    hc.cur_temp = _safe_float(payload, "currtemp") or _safe_float(payload, "curtemp")
    hc.flow_temp = (
        _safe_float(payload, "flowtemp")
        or _safe_float(payload, "curflowtemp")   # simulator + real EMS-ESP key
        or _safe_float(payload, "flowtarget")
    )
    hc.mode = payload.get("mode")
    hc.mode_type = payload.get("modetype")
    hc.heat_slope = _safe_float(payload, "heatslope") or _safe_float(payload, "slope")
    hc.flow_temp_max = _safe_float(payload, "flowtempmax")
    hc.flow_temp_min = _safe_float(payload, "flowtempmin")
    hc.design_temp = _safe_float(payload, "designtemp")
    hc.damped_outdoor_temp = _safe_float(payload, "dampedoutdoortemp")
    hc.summer_mode = _safe_bool(payload, "summermode")
    return hc
