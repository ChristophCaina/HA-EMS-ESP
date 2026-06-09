"""Sensor entities for EMS-ESP Heat Pump integration."""
from __future__ import annotations
import logging
from dataclasses import dataclass
from typing import Any, Callable

from homeassistant.components.sensor import (
    SensorDeviceClass,
    SensorEntity,
    SensorEntityDescription,
    SensorStateClass,
)
from homeassistant.config_entries import ConfigEntry
from homeassistant.const import EntityCategory
from homeassistant.const import (
    UnitOfEnergy,
    UnitOfPower,
    UnitOfTemperature,
    PERCENTAGE,
)
from homeassistant.core import HomeAssistant, callback
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.helpers.update_coordinator import CoordinatorEntity

from .const import DOMAIN, DEVICE_GATEWAY, DEVICE_BOILER, DEVICE_DHW, DEVICE_HC
from .coordinator import EmsEspCoordinator

_LOGGER = logging.getLogger(__name__)


@dataclass(frozen=True)
class EmsEspSensorDescription(SensorEntityDescription):
    """Extended description with value extractor."""
    value_fn: Callable[[Any], Any] | None = None
    device_type: str = DEVICE_BOILER
    is_diagnostic: bool = False


# ------------------------------------------------------------------
# Sensor definitions
# ------------------------------------------------------------------

GATEWAY_SENSORS: tuple[EmsEspSensorDescription, ...] = (
    EmsEspSensorDescription(
        key="gateway_version",
        name="Version",
        icon="mdi:chip",
        device_type=DEVICE_GATEWAY,
        is_diagnostic=True,
        value_fn=lambda d: d["gateway"].version if d["gateway"] else None,
    ),
    EmsEspSensorDescription(
        key="gateway_uptime",
        name="Uptime",
        icon="mdi:timer-outline",
        native_unit_of_measurement="s",
        device_class=SensorDeviceClass.DURATION,
        state_class=SensorStateClass.MEASUREMENT,  # not TOTAL_INCREASING — resets on restart
        device_type=DEVICE_GATEWAY,
        is_diagnostic=True,
        value_fn=lambda d: d["gateway"].uptime_seconds if d["gateway"] else None,
    ),
    EmsEspSensorDescription(
        key="gateway_bus_status",
        name="Bus Status",
        icon="mdi:lan-connect",
        device_type=DEVICE_GATEWAY,
        is_diagnostic=True,
        value_fn=lambda d: d["gateway"].bus_status if d["gateway"] else None,
    ),
)

BOILER_SENSORS: tuple[EmsEspSensorDescription, ...] = (
    EmsEspSensorDescription(
        key="curflowtemp",
        name="Vorlauftemperatur",
        native_unit_of_measurement=UnitOfTemperature.CELSIUS,
        device_class=SensorDeviceClass.TEMPERATURE,
        state_class=SensorStateClass.MEASUREMENT,
        device_type=DEVICE_BOILER,
        value_fn=lambda d: d["boiler"].cur_flow_temp if d["boiler"] else None,
    ),
    EmsEspSensorDescription(
        key="rettemp",
        name="Rücklauftemperatur",
        native_unit_of_measurement=UnitOfTemperature.CELSIUS,
        device_class=SensorDeviceClass.TEMPERATURE,
        state_class=SensorStateClass.MEASUREMENT,
        device_type=DEVICE_BOILER,
        value_fn=lambda d: d["boiler"].ret_temp if d["boiler"] else None,
    ),
    EmsEspSensorDescription(
        key="outdoortemp",
        name="Außentemperatur",
        native_unit_of_measurement=UnitOfTemperature.CELSIUS,
        device_class=SensorDeviceClass.TEMPERATURE,
        state_class=SensorStateClass.MEASUREMENT,
        device_type=DEVICE_BOILER,
        value_fn=lambda d: d["boiler"].outside_temp if d["boiler"] else None,
    ),

    EmsEspSensorDescription(
        key="hpcurrpower",
        name="Leistungsaufnahme (elektrisch)",
        native_unit_of_measurement=UnitOfPower.WATT,
        device_class=SensorDeviceClass.POWER,
        state_class=SensorStateClass.MEASUREMENT,
        device_type=DEVICE_BOILER,
        # EMS-ESP entity: hpcurrpower (W) — always available on WLW186i
        value_fn=lambda d: d["boiler"].hp_power_input if d["boiler"] else None,
    ),
    EmsEspSensorDescription(
        key="hppower",
        name="Thermische Leistung",
        native_unit_of_measurement="kW",
        device_class=SensorDeviceClass.POWER,
        state_class=SensorStateClass.MEASUREMENT,
        device_type=DEVICE_BOILER,
        # EMS-ESP entity: hppower (kW) — available from firmware 12.11.1/9.15.0+
        value_fn=lambda d: d["boiler"].hp_power_output if d["boiler"] else None,
    ),
    EmsEspSensorDescription(
        key="servicecode",
        is_diagnostic=True,
        name="Servicecode",
        icon="mdi:information-outline",
        device_type=DEVICE_BOILER,
        value_fn=lambda d: d["boiler"].service_code if d["boiler"] else None,
    ),
    EmsEspSensorDescription(
        key="nrgconstotal",
        is_diagnostic=True,
        name="Energieverbrauch gesamt (legacy)",
        native_unit_of_measurement=UnitOfEnergy.KILO_WATT_HOUR,
        device_class=SensorDeviceClass.ENERGY,
        state_class=SensorStateClass.TOTAL_INCREASING,
        device_type=DEVICE_BOILER,
        value_fn=lambda d: d["boiler"].nrg_cons_total if d["boiler"] else None,
    ),
    # --- Precise energy (meter* / nrg*) ---
    EmsEspSensorDescription(
        key="nrgtotal",
        name="Wärme gesamt",
        native_unit_of_measurement=UnitOfEnergy.KILO_WATT_HOUR,
        device_class=SensorDeviceClass.ENERGY,
        state_class=SensorStateClass.TOTAL_INCREASING,
        device_type=DEVICE_BOILER,
        value_fn=lambda d: d["boiler"].nrg_total if d["boiler"] else None,
    ),
    EmsEspSensorDescription(
        key="nrgheat",
        name="Wärme Heizen",
        native_unit_of_measurement=UnitOfEnergy.KILO_WATT_HOUR,
        device_class=SensorDeviceClass.ENERGY,
        state_class=SensorStateClass.TOTAL_INCREASING,
        device_type=DEVICE_BOILER,
        value_fn=lambda d: d["boiler"].nrg_heat if d["boiler"] else None,
    ),
    EmsEspSensorDescription(
        key="metertotal",
        name="Strom gesamt",
        native_unit_of_measurement=UnitOfEnergy.KILO_WATT_HOUR,
        device_class=SensorDeviceClass.ENERGY,
        state_class=SensorStateClass.TOTAL_INCREASING,
        device_type=DEVICE_BOILER,
        value_fn=lambda d: d["boiler"].meter_total if d["boiler"] else None,
    ),
    EmsEspSensorDescription(
        key="metercomp",
        name="Strom Kompressor",
        native_unit_of_measurement=UnitOfEnergy.KILO_WATT_HOUR,
        device_class=SensorDeviceClass.ENERGY,
        state_class=SensorStateClass.TOTAL_INCREASING,
        device_type=DEVICE_BOILER,
        value_fn=lambda d: d["boiler"].meter_comp if d["boiler"] else None,
    ),
    EmsEspSensorDescription(
        key="metereheat",
        name="Strom E-Heizer",
        native_unit_of_measurement=UnitOfEnergy.KILO_WATT_HOUR,
        device_class=SensorDeviceClass.ENERGY,
        state_class=SensorStateClass.TOTAL_INCREASING,
        device_type=DEVICE_BOILER,
        value_fn=lambda d: d["boiler"].meter_eheat if d["boiler"] else None,
    ),
    EmsEspSensorDescription(
        key="meterheat",
        name="Strom Heizen",
        native_unit_of_measurement=UnitOfEnergy.KILO_WATT_HOUR,
        device_class=SensorDeviceClass.ENERGY,
        state_class=SensorStateClass.TOTAL_INCREASING,
        device_type=DEVICE_BOILER,
        value_fn=lambda d: d["boiler"].meter_heat if d["boiler"] else None,
    ),
    EmsEspSensorDescription(
        key="metercool",
        name="Strom Kühlen",
        native_unit_of_measurement=UnitOfEnergy.KILO_WATT_HOUR,
        device_class=SensorDeviceClass.ENERGY,
        state_class=SensorStateClass.TOTAL_INCREASING,
        device_type=DEVICE_BOILER,
        value_fn=lambda d: d["boiler"].meter_cool if d["boiler"] else None,
    ),
    # --- Refrigerant temperatures ---
    EmsEspSensorDescription(
        key="hptc3",
        is_diagnostic=True,
        name="Kondensatortemperatur (TC3)",
        native_unit_of_measurement=UnitOfTemperature.CELSIUS,
        device_class=SensorDeviceClass.TEMPERATURE,
        state_class=SensorStateClass.MEASUREMENT,
        device_type=DEVICE_BOILER,
        value_fn=lambda d: d["boiler"].hp_tc3 if d["boiler"] else None,
    ),
    EmsEspSensorDescription(
        key="hptr6",
        is_diagnostic=True,
        name="Heißgastemperatur (TR6)",
        native_unit_of_measurement=UnitOfTemperature.CELSIUS,
        device_class=SensorDeviceClass.TEMPERATURE,
        state_class=SensorStateClass.MEASUREMENT,
        device_type=DEVICE_BOILER,
        value_fn=lambda d: d["boiler"].hp_tr6 if d["boiler"] else None,
    ),
    EmsEspSensorDescription(
        key="hptr4",
        is_diagnostic=True,
        name="Verdampfereingang (TR4)",
        native_unit_of_measurement=UnitOfTemperature.CELSIUS,
        device_class=SensorDeviceClass.TEMPERATURE,
        state_class=SensorStateClass.MEASUREMENT,
        device_type=DEVICE_BOILER,
        value_fn=lambda d: d["boiler"].hp_tr4 if d["boiler"] else None,
    ),
    EmsEspSensorDescription(
        key="hptl2",
        is_diagnostic=True,
        name="Außenlufteintritt (TL2)",
        native_unit_of_measurement=UnitOfTemperature.CELSIUS,
        device_class=SensorDeviceClass.TEMPERATURE,
        state_class=SensorStateClass.MEASUREMENT,
        device_type=DEVICE_BOILER,
        value_fn=lambda d: d["boiler"].hp_tl2 if d["boiler"] else None,
    ),
    # --- Pumps ---
    EmsEspSensorDescription(
        key="heatingpumpmod",
        is_diagnostic=True,
        name="Heizungspumpe Modulation",
        native_unit_of_measurement=PERCENTAGE,
        state_class=SensorStateClass.MEASUREMENT,
        icon="mdi:pump",
        device_type=DEVICE_BOILER,
        value_fn=lambda d: d["boiler"].heating_pump_mod if d["boiler"] else None,
    ),
    EmsEspSensorDescription(
        key="hpcompspd",
        is_diagnostic=True,
        name="Kompressor Drehzahl",
        native_unit_of_measurement=PERCENTAGE,
        state_class=SensorStateClass.MEASUREMENT,
        icon="mdi:heat-pump",
        device_type=DEVICE_BOILER,
        value_fn=lambda d: d["boiler"].hp_compressor_spd if d["boiler"] else None,
    ),
    EmsEspSensorDescription(
        key="hpactivity",
        name="WP Aktivität",
        icon="mdi:information-outline",
        device_type=DEVICE_BOILER,
        value_fn=lambda d: d["boiler"].hp_activity if d["boiler"] else None,
    ),
    # --- Statistics ---
    EmsEspSensorDescription(
        key="burnstarts",
        is_diagnostic=True,
        name="Kompressorstarts",
        icon="mdi:counter",
        state_class=SensorStateClass.TOTAL_INCREASING,
        device_type=DEVICE_BOILER,
        value_fn=lambda d: d["boiler"].burn_starts if d["boiler"] else None,
    ),
    EmsEspSensorDescription(
        key="burnworkmin",
        is_diagnostic=True,
        name="Kompressor Laufzeit",
        native_unit_of_measurement="min",
        icon="mdi:timer",
        state_class=SensorStateClass.TOTAL_INCREASING,
        device_type=DEVICE_BOILER,
        value_fn=lambda d: d["boiler"].burn_work_min if d["boiler"] else None,
    ),
    EmsEspSensorDescription(
        key="cop_current",
        name="COP aktuell",
        icon="mdi:heat-pump",
        state_class=SensorStateClass.MEASUREMENT,
        device_type=DEVICE_BOILER,
        # Calculated: hppower (kW thermal) / hpcurrpower (W electrical)
        # Only valid when compressor is running (hpcurrpower > 0)
        value_fn=lambda d: (
            round(d["boiler"].hp_power_output / (d["boiler"].hp_power_input / 1000), 2)
            if d["boiler"]
            and d["boiler"].hp_power_output is not None
            and d["boiler"].hp_power_input is not None
            and d["boiler"].hp_power_input > 0
            else None
        ),
    ),
    EmsEspSensorDescription(
        key="cop_seasonal",
        name="Jahresarbeitszahl (SPF)",
        icon="mdi:chart-line",
        state_class=SensorStateClass.MEASUREMENT,
        device_type=DEVICE_BOILER,
        # Calculated: nrgtotal (kWh thermal) / metertotal (kWh electrical)
        # metertotal preferred (precise), falls back to nrgconstotal (legacy)
        # Both counters must be > 0 and result must be plausible (1.0–8.0)
        value_fn=lambda d: (
            lambda thermal, electrical: (
                round(thermal / electrical, 2)
                if electrical > 0 and 1.0 <= thermal / electrical <= 8.0
                else None
            )
        )(
            d["boiler"].nrg_total,
            d["boiler"].meter_total or d["boiler"].nrg_cons_total
        )
        if d["boiler"]
        and d["boiler"].nrg_total is not None
        and d["boiler"].nrg_total > 0
        and (d["boiler"].meter_total or d["boiler"].nrg_cons_total)
        else None,
    ),
    EmsEspSensorDescription(
        key="selflowtemp",
        name="Vorlauf Solltemperatur",
        native_unit_of_measurement=UnitOfTemperature.CELSIUS,
        device_class=SensorDeviceClass.TEMPERATURE,
        state_class=SensorStateClass.MEASUREMENT,
        device_type=DEVICE_BOILER,
        value_fn=lambda d: d["boiler"].sel_flow_temp if d["boiler"] else None,
    ),
)

DHW_SENSORS: tuple[EmsEspSensorDescription, ...] = (
    EmsEspSensorDescription(
        key="dhw_curtemp",
        name="Warmwasser Ist-Temperatur",
        native_unit_of_measurement=UnitOfTemperature.CELSIUS,
        device_class=SensorDeviceClass.TEMPERATURE,
        state_class=SensorStateClass.MEASUREMENT,
        device_type=DEVICE_DHW,
        value_fn=lambda d: d["dhw"].cur_temp if d["dhw"] else None,
    ),
    EmsEspSensorDescription(
        key="dhw_curtemp2",
        name="Warmwasser ext. Temperatur",
        native_unit_of_measurement=UnitOfTemperature.CELSIUS,
        device_class=SensorDeviceClass.TEMPERATURE,
        state_class=SensorStateClass.MEASUREMENT,
        device_type=DEVICE_DHW,
        value_fn=lambda d: d["dhw"].cur_temp2 if d["dhw"] else None,
    ),
    EmsEspSensorDescription(
        key="dhw_settemp",
        name="Warmwasser Stop-Temperatur",
        native_unit_of_measurement=UnitOfTemperature.CELSIUS,
        device_class=SensorDeviceClass.TEMPERATURE,
        state_class=SensorStateClass.MEASUREMENT,
        device_type=DEVICE_DHW,
        value_fn=lambda d: d["dhw"].set_temp if d["dhw"] else None,
    ),
    EmsEspSensorDescription(
        key="dhw_nrg",
        name="WWK Wärme gesamt",
        native_unit_of_measurement=UnitOfEnergy.KILO_WATT_HOUR,
        device_class=SensorDeviceClass.ENERGY,
        state_class=SensorStateClass.TOTAL_INCREASING,
        device_type=DEVICE_DHW,
        value_fn=lambda d: d["dhw"].nrg if d["dhw"] else None,
    ),
    EmsEspSensorDescription(
        key="dhw_meter",
        name="WWK Strom gesamt",
        native_unit_of_measurement=UnitOfEnergy.KILO_WATT_HOUR,
        device_class=SensorDeviceClass.ENERGY,
        state_class=SensorStateClass.TOTAL_INCREASING,
        device_type=DEVICE_DHW,
        value_fn=lambda d: d["dhw"].meter if d["dhw"] else None,
    ),
)


async def async_setup_entry(
    hass: HomeAssistant,
    entry: ConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    coordinator: EmsEspCoordinator = hass.data[DOMAIN][entry.entry_id]

    entities: list[EmsEspSensor] = []

    for desc in GATEWAY_SENSORS:
        entities.append(EmsEspSensor(coordinator, desc))
    for desc in BOILER_SENSORS:
        entities.append(EmsEspSensor(coordinator, desc))
    for desc in DHW_SENSORS:
        entities.append(EmsEspSensor(coordinator, desc))

    # HC sensors are added dynamically when thermostat data arrives
    # For now add HC1 statically (will be extended in next phase)
    entities.append(EmsEspHcSensor(coordinator, hc_id=1, key="seltemp", name="HC1 Solltemperatur",
        unit=UnitOfTemperature.CELSIUS, device_class=SensorDeviceClass.TEMPERATURE,
        value_fn=lambda d, i: d["thermostat"].hcs[i].sel_temp if d["thermostat"] and i in d["thermostat"].hcs else None))
    entities.append(EmsEspHcSensor(coordinator, hc_id=1, key="dampedoutdoortemp", name="HC1 Gedämpfte Außentemp",
        unit=UnitOfTemperature.CELSIUS, device_class=SensorDeviceClass.TEMPERATURE,
        value_fn=lambda d, i: d["thermostat"].hcs[i].damped_outdoor_temp if d["thermostat"] and i in d["thermostat"].hcs else None))
    entities.append(EmsEspHcSensor(coordinator, hc_id=1, key="targetflowtemp", name="HC1 Berechnete Vorlauftemperatur",
        unit=UnitOfTemperature.CELSIUS, device_class=SensorDeviceClass.TEMPERATURE,
        value_fn=lambda d, i: (
            d["thermostat"].target_flow_temp                           # real EMS-ESP: targetflowtemp root
            or (d["thermostat"].hcs[i].flow_temp if i in d["thermostat"].hcs else None)  # simulator: hc1.flowtarget
        ) if d["thermostat"] else None))
    entities.append(EmsEspHcSensor(coordinator, hc_id=1, key="flowtemp", name="HC1 Vorlauftemperatur",
        unit=UnitOfTemperature.CELSIUS, device_class=SensorDeviceClass.TEMPERATURE,
        value_fn=lambda d, i: d["thermostat"].hcs[i].flow_temp if d["thermostat"] and i in d["thermostat"].hcs else None))

    async_add_entities(entities)


class EmsEspSensor(CoordinatorEntity, SensorEntity):
    """Generic EMS-ESP sensor entity."""

    entity_description: EmsEspSensorDescription

    def __init__(
        self,
        coordinator: EmsEspCoordinator,
        description: EmsEspSensorDescription,
    ) -> None:
        super().__init__(coordinator)
        self.entity_description = description
        self._attr_unique_id = f"{coordinator.entry_id}_{description.key}"
        self._attr_has_entity_name = True
        if description.is_diagnostic:
            self._attr_entity_category = EntityCategory.DIAGNOSTIC

    @property
    def device_info(self):
        dt = self.entity_description.device_type
        if dt == DEVICE_GATEWAY:
            return self.coordinator.gateway_device_info
        if dt == DEVICE_DHW:
            return self.coordinator.dhw_device_info
        return self.coordinator.boiler_device_info

    @property
    def native_value(self):
        if self.entity_description.value_fn and self.coordinator.data:
            return self.entity_description.value_fn(self.coordinator.data)
        return None

    @property
    def available(self) -> bool:
        return self.coordinator.gateway_info.online


class EmsEspHcSensor(CoordinatorEntity, SensorEntity):
    """Sensor for a specific heating circuit."""

    def __init__(self, coordinator, hc_id, key, name, unit, device_class, value_fn):
        super().__init__(coordinator)
        self._hc_id = hc_id
        self._key = key
        self._value_fn = value_fn
        self._attr_unique_id = f"{coordinator.entry_id}_hc{hc_id}_{key}"
        self._attr_name = name
        self._attr_native_unit_of_measurement = unit
        self._attr_device_class = device_class
        self._attr_has_entity_name = True

    @property
    def device_info(self):
        return self.coordinator.hc_device_info(self._hc_id)

    @property
    def native_value(self):
        if self.coordinator.data:
            return self._value_fn(self.coordinator.data, self._hc_id)
        return None

    @property
    def available(self) -> bool:
        return self.coordinator.gateway_info.online
