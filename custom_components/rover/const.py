"""Constants for Rover integration."""
from __future__ import annotations

DOMAIN = "rover"

# Identity
IDENTITY_HASH_LEN = 16
DISPLAY_NAME_MAX_LEN = 32

# Users
MAX_ACTIVE_REMOTES = 5
MAX_PENDING_REMOTES = 10
ROLE_OWNER = "owner"
ROLE_REGULAR = "regular"

# Section hashes
SECTION_HASH_LEN = 4
HASH_SERIALIZATION = "canonical_json"

# Devices
SHORT_ID_MAX = 0xFFFF
SHORT_ID_MIN = 1

# Sensors
SENSOR_VALUE_AS_STRING = True
SENSOR_PUSH_INTERVAL = 5.0

# Brightness
BRIGHTNESS_RANGE = (0, 100)

# Volume
VOLUME_RANGE = (0, 100)

# PUSH throttle
PUSH_THROTTLE_MS = 500

# QR
QR_FORMAT_VERSION = 2
DEFAULT_TCP_PORT = 4242
QR_TOKEN_LEN = 4

# Message types
TP_STATUS = 2
TP_PUSH = 3
TP_CONFIG = 4
TP_CMD = 5
TP_PING_PONG = 6
TP_FORBIDDEN = 7
TP_REQ = 8
TP_REGISTER = 9

# Type definitions: type_code -> {domain, name}
TYPE_DEFS = {
    "SW": {"domain": "switch", "name": "Switch"},
    "LT": {"domain": "light", "name": "Light"},
    "CV": {"domain": "cover", "name": "Cover"},
    "CL": {"domain": "climate", "name": "Climate"},
    "LK": {"domain": "lock", "name": "Lock"},
    "MS": {"domain": "media_player", "name": "Media Player"},
    "SC": {"domain": "scene", "name": "Scene"},
    "AL": {"domain": "alarm_control_panel", "name": "Alarm Panel"},
    "SE": {"domain": "sensor", "name": "Sensor"},
    "FN": {"domain": "fan", "name": "Fan"},
    "BT": {"domain": "button", "name": "Button"},
}

DOMAIN_TO_TYPE = {v["domain"]: k for k, v in TYPE_DEFS.items()}
DOMAIN_TO_TYPE["binary_sensor"] = "SE"

TYPE_NAMES = {k: v["name"] for k, v in TYPE_DEFS.items()}
TYPE_TO_DOMAIN = {k: v["domain"] for k, v in TYPE_DEFS.items()}

# Logger hierarchy
LOGGER_ROOT = "custom_components.rover"
LOGGER_RNS = "custom_components.rover.rns"
LOGGER_REG = "custom_components.rover.reg"
LOGGER_TRN = "custom_components.rover.trn"
LOGGER_HAB = "custom_components.rover.hab"
LOGGER_HND = "custom_components.rover.hnd"

# Registry storage
STORAGE_KEY = "rover_registry"
STORAGE_VERSION = 1
