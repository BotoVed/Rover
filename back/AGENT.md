# Rover / back — Agent Instructions

Python-плагин для Home Assistant (custom integration). Подключается к локальной Meshtastic-ноде (USB/TCP), слушает события HA, обменивается с приложением и карточкой поверх LoRa.

## Repository
https://github.com/BotoVed/Rover (монорепо)
Эта папка: `back/`
Локальный путь: `tmp/rover/back/`

## Обязательное чтение перед работой
1. [`../SPEC.md`](../SPEC.md) — спецификация продукта (что строим).
2. [`../DECISIONS.md`](../DECISIONS.md) — журнал архитектурных решений (как и почему).
3. Этот файл — операционные инструкции.

При расхождении приоритет: SPEC → DECISIONS → AGENT.

## Environment
| | |
|---|---|
| OS | Ubuntu 24 (dev) / HAOS (target) |
| Python | 3.12+ |
| HA | Home Assistant 2024.x+ |
| Project | `tmp/rover/back/` (dev) → `<HA_config>/custom_components/rover/` (target) |

## Workflow
```
read AGENT.md + ../SPEC.md + ../DECISIONS.md
→ write/change code
→ lint:    ruff check . && ruff format .
→ test:    pytest -q
→ deploy:  scp -P 222 -r rover/ root@<HAOS>:/config/custom_components/
→ restart: ssh root@<HAOS> -p 222 "ha core restart"
→ logs:    ssh root@<HAOS> -p 222 "ha core logs -f | grep rover"
→ commit + push (patch x.y.1)
→ test → fix → patch x.y.2, x.y.3 …
→ итоговый тест → commit + push (minor x.(y+1).0)
→ git tag back-x.(y+1).0 + GitHub Release с ZIP (для HACS)
→ обновить AGENT.md (после минора) и DECISIONS.md (если меняли логику)
```

```bash
# commit template
git add -A && git commit -m "back vX.Y.Z — description" && git push origin main

# tag + release
git tag back-X.Y.Z && git push origin back-X.Y.Z
# затем GitHub Release с ZIP-архивом папки back/ (для HACS)
```

## Project Structure
```
back/
├── README.md
├── AGENT.md                    — этот файл
├── manifest.json               — манифест HA-интеграции
├── hacs.json                   — манифест для HACS
└── rover/
    ├── __init__.py             — точка входа HA: async_setup, инициализация
    ├── const.py                — все константы: tp-коды, поля, лимиты
    ├── config.py               — загрузка/валидация YAML-конфига плагина
    │
    ├── transport.py            — связь с Meshtastic-нодой (serial/TCP), приём/отправка байт
    ├── codec.py                — MessagePack encode/decode, фрагментация tp=7, сборка
    ├── queue.py                — очередь исходящих, дедуп входящих, повторы, пачки
    │
    ├── registry.py             — DeviceRegistry: short_id ↔ entity_id, типы, маппинг, cfgh
    ├── ha_bridge.py            — мост к HA: вызовы сервисов, подписка на state_changed
    │
    ├── dispatcher.py           — маршрутизация входящих пакетов по tp → handler
    ├── handlers.py             — обработчики: on_cmd, on_ping, on_req_all, on_cfg
    │
    └── logger.py               — настройка логирования
```

11 файлов в `rover/`. Каждый понятен по названию. Если файл начинает делать два дела — делится.

## Application Protocol (Rover поверх Meshtastic)

Транспортный порт: `PRIVATE_APP = 256`, сериализация: **MessagePack**.
Полная спецификация — в `../SPEC.md`. Сводка:

| tp | Направление | Назначение |
|----|-------------|------------|
| 2 STATUS | HA → app | Состояние устройства в ответ на запрос |
| 3 PUSH | HA → app | Изменение состояния (инициативное или после команды) |
| 4 CONFIG | HA → app | Конфиг (META или секции с пагинацией) |
| 5 CMD | app → HA | Команда или запрос |
| 6 PING / PONG | app ↔ HA | Keepalive |
| 7 FRAGMENT | любое | Фрагмент крупного сообщения |

**CONFIRM (tp=1) НЕ используется.** Подтверждение исполнения — это broadcast PUSH с новым состоянием. См. DECISIONS.md → SB-006.

### Совместимость числовых типов
MessagePack кодирует число как Int / Long / UInt в зависимости от размера. **Декодер обязан принимать любой из этих типов** для всех числовых полей.

### Адресация Meshtastic
```
to        = 0xFFFFFFFF   ← broadcast (only mode)
channel   = 0            ← приватный канал (на MVP допустим LongFast, key=AQ==)
portnum   = 256          ← PRIVATE_APP
hop_limit = из конфига, по умолчанию 0
```

### Идентификация устройств
`short_id` — 2-байтовый Int (16 бит). Передаётся как число, не строка.
Алгоритм: первые 2 байта MD5 от `entity_id`. При коллизии — пересчёт с инкрементом солта до уникальности. Назначенный однажды `short_id` за устройством закреплён навсегда.

### Очередь
- Ключ исходящей очереди = `short_id` устройства (для PUSH по устройству).
- Для общих сообщений (CONFIG, STATUS-серия, алерты) — уникальный ключ.
- Новая запись для того же ключа затирает старую, счётчик повторов сбрасывается.
- Первая отправка — немедленно. Повторы — каждые N секунд (настройка, дефолт 15).
- Максимум повторов — настройка, дефолт 5.
- Сообщения в пачке — до 200 байт суммарно.
- Не помещающиеся в пакет — фрагментируются (tp=7).
- Дедуп входящих: обработанные сообщения хранятся 15 минут.

### Жизненный цикл команды
1. Получаем CMD по short_id.
2. Через `ha_bridge` вызываем соответствующий сервис HA.
3. Ждём **500 мс**.
4. Читаем актуальное состояние устройства из HA.
5. Шлём broadcast PUSH с новым состоянием.

CONFIRM не отправляем. PUSH — он же подтверждение для инициатора, он же обновление для остальных фронтов.

### Алерты
- Бэк отслеживает binary_sensor с device_class из списка (door / motion / smoke / gas).
- Пока алерт активен, PUSH с состоянием отправляется **каждые 15 секунд**.
- Несколько активных алертов группируются в одну пачку.
- При снятии алерта — финальный PUSH и остановка повторов.

### Несколько фронтов
- Все на одном приватном канале Meshtastic.
- Бэк не различает фронты по node ID, реестра не ведёт.
- PUSH broadcast — каждый фронт получает.

### Поведение в оффлайне фронта
- Фронт считается оффлайн, если не было PING **более 10 минут**.
- Бэк **не копит** очередь PUSH и алертов в оффлайне.

## Поток данных

### Входящий
```
Meshtastic → transport.py (байты)
          → codec.py (распарсенный dict или собранный из фрагментов)
          → queue.py (дедуп: видели ли уже?)
          → dispatcher.py (по tp)
          → handlers.py (нужный обработчик)
          → ha_bridge.py (вызов сервиса) ИЛИ registry.py (запрос конфига)
          → queue.py (ответный пакет в исходящую очередь)
```

### Исходящий
```
HA state_changed → ha_bridge.py
                → registry.py (найти short_id)
                → queue.py (положить PUSH по ключу short_id)

Таймер каждые N секунд → queue.py
                      → собирает пачку до 200 байт
                      → codec.py (фрагментация если надо)
                      → transport.py (отправка)
```

## Dependencies
```
homeassistant >= 2024.1
meshtastic >= 2.3          # официальная Python библиотека Meshtastic
msgpack >= 1.0
pyserial >= 3.5             # transitive через meshtastic
```

Все зависимости — в `manifest.json` интеграции HA.

## Critical Patterns
- Все async — используем `asyncio`, не блокируем event loop HA.
- Числовые поля MessagePack принимать как Int **или** Long.
- `short_id` — Int, не строка, не hex.
- Broadcast only: `to=0xFFFFFFFF`, `channel=0`.
- Ключ очереди = `short_id`, новая запись затирает старую.
- Дедуп входящих — окно 15 минут.
- Регистрация устройств — однократно, `short_id` не меняется при перезапуске. Хранится в `<HA_config>/.storage/rover.registry`.
- HA не должен ждать сети при старте — `async_setup_entry` возвращает быстро, транспорт инициализируется в фоне.

## Соглашения по коду
- Логика транспорта **не знает** про MessagePack — только `bytes ↔ transport.py`.
- Логика codec **не знает** про очередь — только `dict ↔ codec.py`.
- Логика очереди **не знает** про HA — только `OutPacket ↔ queue.py`.
- Обработчики **не знают** про транспорт — только `dispatcher → handler → ha_bridge/registry/queue`.
- Один файл = одна ответственность.
- `DeviceRegistry` — единственный источник истины по устройствам.

## Тестирование
- **Юнит-тесты** обязательны для `codec.py` и `queue.py` — чистая логика без зависимостей.
- `transport.py`, `ha_bridge.py` — ручное тестирование с реальным железом и HA.
- `dispatcher.py`, `handlers.py` — юнит-тесты с моками `ha_bridge` и `queue`.

## Релизы
При каждом минорном повышении версии:
1. `git tag back-X.Y.0`
2. `git push origin back-X.Y.0`
3. GitHub Release с ZIP-архивом содержимого `back/` (для HACS).
4. Обновить версию в `manifest.json` и `hacs.json`.

## Что обновлять после изменений
- Изменили поведение, поля пакета, тип устройства → **../SPEC.md** + **../DECISIONS.md** (синхронно).
- Изменили команды деплоя, структуру проекта, добавили зависимость, минорное повышение версии → **AGENT.md**.
