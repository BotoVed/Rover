"""Константы протокола Rover.

Все «магические числа» и строки протокола собраны здесь. Менять — только
синхронно с SPEC.md.

См. SPEC.md §4 (типы пакетов), §5 (типы устройств), §7 (очередь).
"""

from __future__ import annotations

# ---------- Типы пакетов (поле tp) ----------

TP_STATUS = 2
TP_PUSH = 3
TP_CONFIG = 4
TP_CMD = 5
TP_PING = 6        # и PONG — тот же tp, направление из контекста
TP_FRAGMENT = 7

# ---------- Имена полей пакетов ----------

F_TP = "tp"
F_ID = "id"            # short_id устройства
F_CMID = "cmid"        # уникальный ID команды (для дедупа)
F_TS = "ts"            # Unix timestamp отправителя
F_HL = "hl"            # hop limit

# Состояние / команды устройств
F_STATE = "s"
F_BRIGHTNESS = "bri"
F_COLOR_TEMP = "ct"
F_TARGET_TEMP = "th"
F_CURRENT_TEMP = "tc"
F_MODE = "md"
F_FAN_MODE = "fn"
F_SPEED = "sp"
F_POSITION = "pos"
F_STATUS = "st"        # cover, alarm
F_VALUE = "v"          # sensor value
F_UNIT = "u"           # sensor unit
F_COMMAND = "cmd"      # open/close/lock/unlock/press
F_PIN = "pin"

# Запросы и конфиг
F_REQ = "req"
F_CFG = "cfg"

# CONFIG-пакет
F_SECTION = "s"        # "meta", "ar", "dev", "mpg", "usr"
F_NAME = "n"
F_GATEWAY = "gw"
F_CHANNEL = "ch"
F_KEY = "key"
F_PERIOD = "upd"
F_RETRIES = "rty"
F_PUSH_ENABLED = "psh"
F_HOP = "hop"
F_CFGH = "cfgh"
F_PAGE = "pg"
F_PAGE_TOTAL = "pgt"
F_DATA = "d"

# Фрагменты
F_FRAG_ID = "fid"
F_FRAG_INDEX = "fi"
F_FRAG_TOTAL = "fn"

# ---------- Типы устройств Rover ----------

DEV_LIGHT = "L"
DEV_SWITCH = "SW"
DEV_CLIMATE = "C"
DEV_WATER_HEATER = "WH"
DEV_FAN = "F"
DEV_COVER = "CV"
DEV_LOCK = "LK"
DEV_BINARY_SENSOR = "BS"
DEV_SENSOR = "S"
DEV_SIREN = "SI"
DEV_BUTTON = "B"
DEV_ALARM = "A"
DEV_HUMIDIFIER = "H"

# Маппинг HA domain → код типа Rover
HA_DOMAIN_TO_DEV_TYPE: dict[str, str] = {
    "light": DEV_LIGHT,
    "switch": DEV_SWITCH,
    "climate": DEV_CLIMATE,
    "water_heater": DEV_WATER_HEATER,
    "fan": DEV_FAN,
    "cover": DEV_COVER,
    "lock": DEV_LOCK,
    "binary_sensor": DEV_BINARY_SENSOR,
    "sensor": DEV_SENSOR,
    "siren": DEV_SIREN,
    "button": DEV_BUTTON,
    "scene": DEV_BUTTON,
    "alarm_control_panel": DEV_ALARM,
    "humidifier": DEV_HUMIDIFIER,
}

# ---------- Лимиты протокола ----------

SHORT_ID_MAX = 0xFFFF              # 2-байтовый Int
PING_INTERVAL_SEC = 120             # фронт пингует раз в 2 минуты
OFFLINE_THRESHOLD_SEC = 600         # 10 минут без PING → фронт оффлайн
ALERT_REPEAT_SEC = 15               # повтор активных алертов
DEDUP_WINDOW_SEC = 15 * 60          # окно дедупа входящих
FRAGMENT_TIMEOUT_SEC = 60           # таймаут сборки фрагментов
HA_SETTLE_DELAY_SEC = 0.5           # пауза перед чтением состояния после команды

# Дефолтные значения, переопределяемые в конфиге плагина
DEFAULT_QUEUE_PERIOD = 15           # период повторов очереди, сек
DEFAULT_MAX_RETRIES = 5             # максимум повторов
DEFAULT_HOP_LIMIT = 0               # прямая связь

# ---------- Транспорт Meshtastic ----------

MESHTASTIC_PRIVATE_APP_PORT = 256
MESHTASTIC_BROADCAST_ADDR = 0xFFFFFFFF

# ---------- HA integration ----------

DOMAIN = "rover"

# Ключи конфига для config_flow
CONF_PORT = "port"                   # путь к устройству или TCP-адрес
CONF_CONN_TYPE = "conn_type"         # "serial" или "tcp"
CONF_CHANNEL = "channel"             # имя приватного канала Meshtastic
CONF_PSK = "psk"                     # ключ канала (base64)
CONF_HOME_NAME = "home_name"         # отображаемое имя дома (для META)
CONF_HOP_LIMIT = "hop_limit"         # 0..7
CONF_QUEUE_PERIOD = "queue_period"   # период повторов очереди, сек
CONF_MAX_RETRIES = "max_retries"     # максимум повторов
CONF_PUSH_ENABLED = "push_enabled"   # включена ли инициативная отправка PUSH

# Дефолты для config_flow (если значения не заданы пользователем)
DEFAULT_CONN_TYPE = "serial"
DEFAULT_CHANNEL = "LongFast"
DEFAULT_PSK = "AQ=="
DEFAULT_HOME_NAME = "Мой дом"
DEFAULT_PUSH_ENABLED = True
