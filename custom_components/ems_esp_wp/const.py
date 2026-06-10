"""Constants for EMS-ESP Heat Pump Integration."""

DOMAIN = "ems_esp_wp"
CONF_BASE_TOPIC = "base_topic"
CONF_DEVICE_NAME = "device_name"
CONF_EMS_ESP_IP = "ems_esp_ip"

DEFAULT_BASE_TOPIC = "ems-esp"
DEFAULT_PORT = 1883

# EMS-ESP version thresholds
VERSION_DHW_NESTED = (3, 6, 0)   # From this version onwards, DHW is nested in boiler_data
VERSION_PRODUCT_ID = (3, 4, 0)   # From this version onwards, product_id is in payloads

# MQTT sub-topics (relative to base_topic)
TOPIC_STATUS = "status"
TOPIC_INFO = "info"
TOPIC_HEARTBEAT = "heartbeat"
TOPIC_HEATING_ACTIVE = "heating_active"
TOPIC_TAPWATER_ACTIVE = "tapwater_active"
TOPIC_BOILER_DATA = "boiler_data"
TOPIC_BOILER_DATA_WW = "boiler_data_ww"      # v3.5 style (legacy)
TOPIC_HEATING_ACTIVE = "heating_active"
TOPIC_TAPWATER_ACTIVE = "tapwater_active" 
TOPIC_THERMOSTAT_DATA = "thermostat_data"
TOPIC_MIXER_DATA = "mixer_data"
TOPIC_SOLAR_DATA = "solar_data"
TOPIC_SHOWER_DATA = "shower_data"

# Device type identifiers (used for HA device registry)
DEVICE_GATEWAY = "gateway"
DEVICE_BOILER = "boiler"
DEVICE_DHW = "dhw"
DEVICE_THERMOSTAT = "thermostat"
DEVICE_HC = "hc"          # prefix, e.g. hc1, hc2

# Known EMS product IDs → friendly model names
# Source: EMS-ESP device list / EMS bus product registry
PRODUCT_ID_NAMES = {
    # Buderus / Bosch heat pumps
    123: "Buderus WLW186i-12",
    124: "Buderus WLW186i-14",
    125: "Buderus WLW186i-17",
    95:  "Buderus Logatherm WPL",
    # Buderus boilers
    115: "Buderus GB172",
    72:  "Buderus GB162",
    # Nefit
    203: "Nefit Proline HRC",
    # Bosch
    170: "Bosch Condens 7000i",
    # Thermostats
    77:  "Buderus RC310",
    79:  "Buderus RC300",
    93:  "Buderus RC200",
    69:  "Nefit ModuLine 300",
    # Fallback handled in code
}

# Thermostat mode mappings
THERMOSTAT_MODES = {
    "auto": "auto",
    "day": "heat",
    "night": "cool",  # mapped to cool as closest HA equivalent
    "eco": "eco",
    "nofrost": "off",
    "manual": "heat",
    "comfort": "heat",
    "holiday": "off",
}

HA_TO_EMS_MODES = {v: k for k, v in THERMOSTAT_MODES.items()}

# Units of measurement
UOM_TEMP = "°C"
UOM_POWER = "W"
UOM_ENERGY = "kWh"
UOM_PERCENT = "%"
UOM_HOURS = "h"
UOM_BAR = "bar"
UOM_RPM = "rpm"
