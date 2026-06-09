"""Data models for EMS-ESP devices."""
from __future__ import annotations
from dataclasses import dataclass, field
from typing import Any


@dataclass
class EmsEspGatewayInfo:
    """Data from info + heartbeat topics."""
    version: str = "unknown"
    hostname: str = "ems-esp"
    version_tuple: tuple = (0, 0, 0)
    bus_status: str = "unknown"
    uptime: str = "0"
    uptime_seconds: int = 0
    wifi_rssi: int = 0
    free_mem: int = 0
    mqtt_fails: int = 0
    online: bool = False

    def parse_version(self) -> None:
        """Parse version string like '3.7.3' into tuple."""
        try:
            parts = self.version.split(".")
            self.version_tuple = tuple(int(p) for p in parts[:3])
        except (ValueError, AttributeError):
            self.version_tuple = (0, 0, 0)

    @property
    def supports_dhw_nested(self) -> bool:
        """DHW data nested in boiler_data from v3.6.0+."""
        from .const import VERSION_DHW_NESTED
        return self.version_tuple >= VERSION_DHW_NESTED

    @property
    def supports_product_id(self) -> bool:
        """Product ID in payloads from v3.4.0+."""
        from .const import VERSION_PRODUCT_ID
        return self.version_tuple >= VERSION_PRODUCT_ID


@dataclass
class EmsEspBoilerData:
    """Parsed boiler data (heating side)."""
    # Temperatures
    cur_flow_temp: float | None = None
    ret_temp: float | None = None
    outside_temp: float | None = None
    heat_exchanger_temp: float | None = None
    # Operating state
    heating_active: bool = False
    service_code: str | None = None
    service_code_number: int | None = None
    # Heat pump specific
    hp_compressor_on: bool = False
    hp_circ_pump_on: bool = False
    hp_activity: str | None = None
    hp_cop: float | None = None
    hp_power_input: float | None = None
    hp_power_output: float | None = None
    # Settings
    hp_max_power: int | None = None
    silent_mode: int | None = None
    pv_mode: str | None = None
    # Energy counters
    nrg_cons_total: float | None = None
    nrg_heat_total: float | None = None
    # Refrigerant circuit temperatures
    hp_tc0: float | None = None      # Kältemittelrücklauf
    hp_tc1: float | None = None      # Kältemittelvorlauf
    hp_tc3: float | None = None      # Kondensatortemperatur
    hp_tr1: float | None = None      # Kompressortemperatur
    hp_tr3: float | None = None      # Kältemittel flüssig
    hp_tr4: float | None = None      # Verdampfereingang
    hp_tr5: float | None = None      # Kompressoreingang (Sauggas)
    hp_tr6: float | None = None      # Kompressorausgang (Heißgas)
    hp_tl2: float | None = None      # Außenlufteintritt
    hp_pl1: float | None = None      # Niederdrucktemperatur
    hp_ph1: float | None = None      # Hochdrucktemperatur
    hp_ta4: float | None = None      # Kondensatwanne
    # Flow temps
    sel_flow_temp: float | None = None    # selflowtemp
    target_flow_temp: float | None = None # targetflowtemp (thermostat)
    # Pumps
    heating_pump: bool = False
    heating_pump_mod: int | None = None   # %
    hp_circ_spd: int | None = None        # %
    hp_compressor_spd: int | None = None  # %
    # Activity / Status
    hp_activity: str | None = None        # off|heating|cooling|hot water|defrost
    # Energy — precise (2 decimal)
    nrg_total: float | None = None        # thermal total kWh
    nrg_heat: float | None = None         # thermal heating kWh
    nrg_cool: float | None = None         # thermal cooling kWh
    meter_total: float | None = None      # electrical total kWh
    meter_comp: float | None = None       # electrical compressor kWh
    meter_eheat: float | None = None      # electrical aux heater kWh
    meter_heat: float | None = None       # electrical heating kWh
    meter_cool: float | None = None       # electrical cooling kWh
    # Energy — legacy (integer kWh)
    nrg_cons_comp_total: float | None = None
    nrg_cons_comp_heating: float | None = None
    aux_elec_heat_nrg_cons_total: float | None = None
    # Statistics
    burn_starts: int | None = None
    burn_work_min: int | None = None      # minutes
    # product id for device name lookup
    product_id: int | None = None
    raw: dict = field(default_factory=dict)


@dataclass
class EmsEspDhwData:
    """Parsed DHW (Domestic Hot Water) data."""
    # Temperatures
    cur_temp: float | None = None
    set_temp: float | None = None
    # State
    active: bool = False
    activated: bool = True
    # Settings
    comfort: str | None = None
    # Temperatures
    cur_temp2: float | None = None    # external sensor
    set_temp: float | None = None     # stop temp
    # Energy — precise
    nrg: float | None = None          # thermal kWh (precise)
    meter: float | None = None        # electrical kWh (precise)
    nrg_comp: float | None = None     # electrical compressor kWh
    aux_elec: float | None = None     # electrical aux heater kWh
    # Legacy
    nrg_total: float | None = None
    product_id: int | None = None
    raw: dict = field(default_factory=dict)


@dataclass
class EmsEspHcData:
    """Parsed Heating Circuit data (HC1..HC4)."""
    hc_id: int = 1
    # Temperatures
    sel_temp: float | None = None
    cur_temp: float | None = None
    flow_temp: float | None = None
    # State & mode
    mode: str | None = None
    mode_type: str | None = None
    heat_slope: float | None = None
    flow_temp_max: float | None = None
    flow_temp_min: float | None = None
    design_temp: float | None = None
    summer_mode: bool = False
    # Damped outdoor temp
    damped_outdoor_temp: float | None = None
    raw: dict = field(default_factory=dict)


@dataclass
class EmsEspThermostatData:
    """Parsed thermostat data — contains multiple HCs."""
    hcs: dict[int, EmsEspHcData] = field(default_factory=dict)
    product_id: int | None = None
    target_flow_temp: float | None = None   # calculated by controller
    raw: dict = field(default_factory=dict)
