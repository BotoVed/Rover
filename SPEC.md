# Rover — Specification

**Версия спецификации:** 0.3.0 (Reticulum-архитектура)
**Статус:** черновик, готов для реализации с нуля
**Лицензия:** GPL v3

---

## 1. Обзор

**Rover = Remote Over Radio.** Кастомная интеграция Home Assistant для управления умным домом через mesh-сети **Reticulum/LXMF**. Целевая аудитория — дома на колёсах (RV) и любые места без интернета.

Три репозитория:

| Репозиторий            | Назначение                          | Стек                     |
|------------------------|-------------------------------------|--------------------------|
| `BotoVed/Rover`        | HA-интеграция (back)                | Python                   |
| `BotoVed/Rover-Card`   | Lovelace-карточка                   | TypeScript + LitElement  |
| `BotoVed/Rover-App`    | Android-приложение                  | Kotlin (на базе Columba) |

Главный репозиторий — `BotoVed/Rover`. SPEC и DECISIONS живут там.

---

## 2. Архитектура

```
┌─────────────┐                              ┌─────────────┐
│  Rover-App  │◄──── LXMF over Reticulum ───►│ Rover (HA)  │
│  (Android)  │                              │             │
└─────────────┘                              │   Registry  │
                                             │   Handlers  │
┌─────────────┐                              │   Bridge    │
│ Rover-Card  │◄────── HA service calls ────►│             │
│  (Lovelace) │                              └──────┬──────┘
└─────────────┘                                     │
                                              HA state/services
                                                    │
                                              ┌─────▼─────┐
                                              │ Устройства │
                                              │   (HA)    │
                                              └───────────┘
```

**Принципиальное разделение:**
- **Rover-App** общается с HA только по Reticulum/LXMF. Не знает про HA, не знает про entity_id.
- **Rover-Card** общается с HA штатным образом (state, service calls). Не знает про Reticulum.
- **Rover (HA)** — мост между ними. Источник истины для конфигурации устройств и состояний.

---

## 3. Транспортный стек: Reticulum + LXMF

### 3.1. Что используем

- **RNS (Reticulum Network Stack)** — нижний слой: идентичности, маршрутизация, доставка, шифрование.
- **LXMF (Lightweight eXtensible Message Format)** — верхний слой: store-and-forward сообщения, доставка с подтверждением, поля произвольной структуры.

### 3.2. Что НЕ пишем сами

Reticulum / LXMF берут на себя:

- Шифрование (end-to-end по умолчанию, Forward Secrecy)
- Доставку и подтверждение (delivery proof)
- Фрагментацию сообщений
- Маршрутизацию через несколько hop'ов (до 128)
- Защиту от подделки отправителя (Ed25519-подписи)
- Дедупликацию по message-id (SHA-256 от destination + source + payload)
- Store-and-forward (через Propagation Nodes, если развернуты в сети)

Наш протокол **не реализует** ACK, fragment, retry, queue с приоритетами. Это всё уже есть в LXMF.

### 3.3. Что пишем мы

- Application layer: типы сообщений (`tp=2..6, 8, 9`), формат полей
- Регистр устройств и пользователей на стороне HA
- Маппинг entity_id ↔ short_id
- Логику команд (CMD → service call) и состояний (state change → PUSH)
- Онбординг и approval pending-remote'ов
- HA UI (config_flow, options_flow)

### 3.4. Network interfaces

Reticulum поддерживает множество интерфейсов одновременно (RNode/LoRa, TCP/IP, WiFi, I2P, serial). Их выбор и конфигурация — на уровне `~/.reticulum/config`, **прозрачно для нашего кода**.

Типичный сценарий для RV:
- В дороге: RNode (LoRa) — телефон владельца через BLE-связанный RNode общается с домашним HA через сетку
- Дома: WiFi — телефон в локалке мгновенно достигает HA через TCP-интерфейс Reticulum

Один и тот же identity на телефоне работает через любой доступный интерфейс. Наш код этого не различает.

### 3.5. LXMF структура сообщения

LXMF определяет следующие поля:

| Поле       | Тип       | Назначение в Rover                            |
|------------|-----------|-----------------------------------------------|
| Destination| 16 байт   | Identity получателя (HA или конкретный App)   |
| Source     | 16 байт   | Identity отправителя (автоматически от LXMF)  |
| Signature  | 64 байта  | Ed25519-подпись (автоматически)               |
| Timestamp  | double    | UNIX time                                     |
| Content    | bytes     | Не используется (оставляем пустым)            |
| Title      | bytes     | Не используется (оставляем пустым)            |
| Fields     | msgpack   | **Наш payload** (см. раздел 6)                |

Весь протокол Rover живёт внутри `Fields`. Структура: msgpack-словарь с ключом `tp` и type-specific полями.

**Python API (LXMF ≥0.9.6):**
```python
# Инициализация (один раз при старте интеграции)
RNS.Reticulum(configdir=path)
router = LXMF.LXMRouter(storagepath=path, enforce_stamps=False)
local_identity = RNS.Identity()  # или загруженная из файла
local_delivery_dest = router.register_delivery_identity(
    local_identity,
    display_name="Rover Hub"
)
router.register_delivery_callback(on_inbound_message)

# Отправка сообщения конкретному remote
def send_message(remote_hash: bytes, fields: dict) -> bool:
    # 1) Получить identity получателя через recall.
    #    Identity появляется в кеше после announce от remote.
    remote_identity = RNS.Identity.recall(remote_hash)
    if remote_identity is None:
        # Путь и identity ещё неизвестны — запросить
        RNS.Transport.request_path(remote_hash)
        return False  # сообщение не отправлено, попробовать позже

    # 2) Собрать Destination на стороне отправителя
    remote_dest = RNS.Destination(
        remote_identity,
        RNS.Destination.OUT,
        RNS.Destination.SINGLE,
        "lxmf", "delivery"
    )

    # 3) Создать LXMessage. content/title — пустые (наш payload в fields)
    msg = LXMF.LXMessage(
        remote_dest,
        local_delivery_dest,
        "",  # content
        "",  # title
        desired_method=LXMF.LXMessage.DIRECT
    )
    msg.fields = fields  # msgpack-словарь с tp и type-specific полями

    msg.register_delivery_callback(on_delivered)
    msg.register_failed_callback(on_failed)

    # 4) Передать роутеру — он сам сделает упаковку, шифрование, retry
    router.handle_outbound(msg)
    return True
```

**Важно:** `destination` в `LXMessage(...)` — это **только `RNS.Destination` объект**, не bytes-hash. Reticulum требует знать публичный ключ получателя для шифрования. Identity появляется в локальном кеше после `announce` от remote или после успешного `RNS.Transport.request_path(...)`. Если identity ещё не известна — сообщение отправить нельзя, нужно подождать path discovery (обычно секунды-минуты в зависимости от mesh-сети).

На практике это означает: первое сообщение к новому remote может потребовать предварительного `request_path` и небольшой задержки. Логика отправки в `rns_transport.py` должна это учитывать — например, ставить сообщение в локальную очередь и повторять попытку через 3-5 секунд (но не накапливая бесконечно — см. DECISIONS 055).

---

## 4. Идентичности и онбординг

### 4.1. Identity модель

- **HA-сервер** имеет **одну Identity**, создаётся при первой настройке интеграции, сохраняется в `<config>/custom_components/rover/.reticulum/`.
- **Каждый телефон** имеет **свою Identity**, создаётся при первом запуске Rover-App.
- Идентификаторы — 16 байт (Reticulum destination hash). В UI отображаются как hex-строка (32 символа) или QR-код.

### 4.2. Онбординг (пошагово)

1. **Установка интеграции.** Админ устанавливает Rover через HACS, добавляет интеграцию в HA. При первом запуске бэк генерирует RNS Identity для сервера, сохраняет в `.reticulum/`.

2. **Настройка через options_flow.** Админ открывает экран настроек интеграции — видит:
   - QR-код с destination hash HA-сервера
   - Display name сервера (редактируемый)
   - Список активных remote'ов (пусто)
   - Список pending-remote'ов (пусто)
   - Конфигурацию устройств / пользователей / общие настройки

3. **Установка приложения.** Пользователь устанавливает Rover-App на телефон. При первом запуске:
   - Приложение генерирует свою RNS Identity
   - Открывает QR-сканер для добавления сервера

4. **Сканирование QR.** Пользователь сканирует QR с экрана HA. Приложение запоминает destination hash сервера.

   **Формат QR:** `{"rvr": {"fmt": 1, "dst": "a1b2c3d4...", "nm": "Дом на колёсах"}}`

5. **REGISTER.** Приложение отправляет HA сообщение `tp=9 REGISTER` с display name пользователя и опциональной версией App.

6. **Pending или auto-approve.**
   - Если активных remote'ов **0** → HA автоматически одобряет, назначает роль **owner**, добавляет в активные, отправляет полный CONFIG.
   - Если активных remote'ов **≥1** → HA добавляет запрос в pending list. Owner получает PUSH-уведомление в HA UI «Новый запрос от <имя>».

7. **Approve owner'ом.** Owner открывает HA UI, видит pending request, нажимает «Одобрить». HA переводит запись в активные (роль **regular**), отправляет полный CONFIG этому телефону.

8. **Лимит 5.** Если активных уже 5 — owner не может одобрить нового без удаления одного из активных. UI показывает «Активных: 5/5».

### 4.3. Pending list

- Лимит pending — **10 запросов** (защита от спама).
- При попытке зарегистрироваться, если pending уже полон — HA отклоняет (молча, без ответа).
- Owner может удалить pending-запись из UI без одобрения.

### 4.4. Отзыв доступа

Owner может удалить активного remote через HA UI. После удаления:
- Запись удаляется из реестра пользователей
- Identity hash добавляется в blacklist (опционально, отложено)
- При следующей попытке REGISTER от того же identity — снова pending

### 4.5. Восстановление identity

- На стороне HA — если файлы identity в `.reticulum/` утеряны, **все remote'ы становятся недоступны** (новый identity = новый адрес). Регистрация заново.
- На стороне App — пользователь может экспортировать/импортировать identity между устройствами (фича Columba).
- В Options Flow HA — кнопка «Экспорт identity» для backup.

---

## 5. Роли

| Роль    | Видимость устройств | Управление другими remote'ами |
|---------|---------------------|-------------------------------|
| owner   | все                 | да (approve, revoke)          |
| regular | все                 | нет                           |

**Заметка о per-remote whitelist'ах.** В версии 0.3.0 все одобренные remote'ы видят один и тот же список устройств. Возможность давать каждому remote индивидуальный набор устройств — в бэклоге, будет добавлена без breaking changes (расширение секции `u`).

---

## 6. Протокол сообщений

Все сообщения летят как LXMF Fields (msgpack-словарь).

### 6.1. Сводная таблица

| tp | Имя       | Направление    | Назначение                                  |
|----|-----------|----------------|---------------------------------------------|
| 2  | STATUS    | HA → App       | Серия состояний (ответ на REQ)              |
| 3  | PUSH      | HA → App       | Уведомление об изменении state              |
| 4  | CONFIG    | HA → App       | Содержимое секции (m/u/a/d)                 |
| 5  | CMD       | App → HA       | Команда устройству                          |
| 6  | PING/PONG | App ↔ HA       | Обмен хешами секций                         |
| 8  | REQ       | App → HA       | Запрос секции конфигурации                  |
| 9  | REGISTER  | App → HA       | Запрос регистрации нового remote'а          |

Зарезервировано (на будущее): `tp=1, 7, 10+`.

### 6.2. tp=2 STATUS (HA → App)

Серия состояний нескольких устройств. Ответ на REQ или инициативная отправка после approval (полный snapshot всех устройств).

```
{
  "tp": 2,
  "s": [
    {"id": 49283, "v": "on",  "extra": ...},
    {"id": 7150,  "v": "85.5", ...},
    ...
  ]
}
```

Поля внутри элемента `s[i]` зависят от типа устройства (см. раздел 8).

### 6.3. tp=3 PUSH (HA → App)

Одно изменение состояния. HA отправляет этот пакет каждому одобренному remote'у (unicast loop, max 5) при изменении state любого зарегистрированного устройства.

```
{
  "tp": 3,
  "id": 49283,
  "v": "on"
}
```

Если LXMF доставка не удалась — **не повторяем**. При следующем PING/PONG телефон обнаружит расхождение хешей и запросит обновление через REQ.

**Throttle:** per-device 500 мс. Если state меняется чаще — предыдущее значение затирается, отправляется только последнее после задержки. Для SE — max 1 PUSH / 5 сек.

### 6.4. tp=4 CONFIG (HA → App)

Содержимое одной секции. Отправляется в ответ на `tp=8 REQ` или при первом одобрении remote'а (тогда HA шлёт все 4 секции последовательно).

```
{
  "tp": 4,
  "section": "d",
  "h": "78ab",
  "data": [...]
}
```

Поле `h` — хеш этой секции (MD5[:4], 4 hex-символа). Используется клиентом для PING/PONG-сверки.

Секции:
- `m` (meta): метаданные сервера
- `u` (users): список одобренных remote'ов
- `a` (areas): список зон
- `d` (devices): список устройств

Подробное содержание секций — раздел 7.

### 6.5. tp=5 CMD (App → HA)

Команда устройству.

```
{
  "tp": 5,
  "id": 49283,
  "s": true
}
```

Поля кроме `tp` и `id` — зависят от типа устройства (см. раздел 8).

**Дедупликация:** LXMF автоматически отбрасывает дубликаты по message-id. Поле `cmid` не нужно.

**Authorization:** HA берёт `source` identity hash из LXMF envelope, проверяет — есть ли в списке одобренных. Если нет — пакет игнорируется (без ответа).

### 6.6. tp=6 PING/PONG (App ↔ HA)

Обмен хешами секций для синхронизации.

**PING (App → HA):**
```
{
  "tp": 6,
  "h": {
    "m": "ab12",
    "u": "cd34",
    "a": "ef56",
    "d": "78ab"
  }
}
```

**PONG (HA → App):**
```
{
  "tp": 6,
  "h": {
    "m": "ab12",
    "u": "newh",
    "a": "ef56",
    "d": "78ab"
  }
}
```

Клиент сравнивает свои хеши с присланными. Различающиеся секции → отдельный `tp=8 REQ` для каждой.

**Инициативный PONG.** HA отправляет PONG всем одобренным remote'ам **без запроса**, когда хеш любой секции меняется (например, добавили устройство). Это позволяет remote'ам узнать об изменениях быстро без polling'а.

### 6.7. tp=8 REQ (App → HA)

Запрос секции конфигурации.

```
{
  "tp": 8,
  "section": "d"
}
```

Возможные значения `section`: `m`, `u`, `a`, `d`.

HA отвечает `tp=4 CONFIG` с запрошенной секцией.

### 6.8. tp=9 REGISTER (App → HA)

Запрос регистрации нового remote'а.

```
{
  "tp": 9,
  "name": "Иван",
  "ver": "0.3.0"
}
```

- `name` — display name пользователя (обязательно).
- `ver` — версия App (опционально, для будущей совместимости).

Поведение HA — см. раздел 4.2.

---

## 7. Секции конфигурации

### 7.1. Секция m (meta)

```
{
  "brand": "Rover",
  "version": "0.3.0",
  "server_name": "Дом на колёсах"
}
```

Хеш: MD5[:4] от канонического JSON (`sort_keys=True`, `ensure_ascii=False`, `separators=(',',':')`).

### 7.2. Секция u (users)

```
[
  {"hash": "1a2b3c...", "name": "Иван", "role": "owner"},
  {"hash": "4d5e6f...", "name": "Маша", "role": "regular"}
]
```

`hash` — Reticulum identity hash в hex (32 символа).

Видимость: все одобренные remote'ы видят полный список. В версии 0.3.0 это household-friendly, не privacy-критично. При желании в будущем можно скрыть других — без breaking change.

### 7.3. Секция a (areas)

```
[
  {"id": 1, "name": "Кухня"},
  {"id": 2, "name": "Спальня"},
  {"id": 3, "name": "Улица"}
]
```

### 7.4. Секция d (devices)

```
[
  {"id": 49283, "n": "Розетка", "t": "SW", "a": 1},
  {"id": 7150,  "n": "Температура", "t": "SE", "a": 1, "u": "°C"},
  ...
]
```

Поля:
- `id` — short_id (int 0-65535)
- `n` — отображаемое имя
- `t` — тип устройства (см. раздел 8)
- `a` — id области (или null)
- type-specific поля (например, `u` — единица измерения для SE)

### 7.5. Расчёт хешей

Алгоритм для каждой секции:
1. Сериализовать содержимое секции в **канонический JSON**:
   - `json.dumps(data, sort_keys=True, ensure_ascii=False, separators=(',',':'))`
2. UTF-8 bytes
3. MD5(bytes)
4. Взять первые 2 байта (4 hex-символа)

Хеши кешируются в registry и пересчитываются только при мутации данных.

Каждое изменение содержимого → новый хеш → инициативный PONG всем активным remote'ам.

---

## 8. Типы устройств

Кодировка типа — 2 символа в поле `t`.

| Код | Тип                | HA domain     |
|-----|--------------------|---------------|
| SW  | Switch             | switch        |
| LT  | Light              | light         |
| CV  | Cover              | cover         |
| CL  | Climate            | climate       |
| LK  | Lock               | lock          |
| MS  | Media player       | media_player  |
| SC  | Scene              | scene         |
| AL  | Alarm panel        | alarm_control_panel |
| SE  | Sensor             | sensor, binary_sensor |
| FN  | Fan                | fan           |
| BT  | Button             | button        |

### 8.1. Поля CMD по типам

| Тип | CMD-поля | Пример |
|-----|----------|--------|
| SW  | `s: bool` | `{tp:5, id:1, s:true}` |
| LT  | `s: bool`, `b?: int 0-100`, `ct?: int` (K), `rgb?: [r,g,b] int 0-255`, `ef?: str` | `{tp:5, id:2, s:true, b:75, ct:2700}` |
| CV  | `cv: "open"\|"close"\|"stop"\|"set"`, `p?: int 0-100`, `t?: int 0-100` (tilt) | `{tp:5, id:3, cv:"set", p:50}` |
| CL  | `hvac?: str`, `t?: float`, `th?: float` (temp high), `tl?: float` (temp low), `fan?: str`, `preset?: str`, `swing_h?: str`, `swing_v?: str` | `{tp:5, id:4, hvac:"heat", t:22.5}` |
| LK  | `s: bool` (true=locked) | `{tp:5, id:5, s:true}` |
| MS  | `ms: "play"\|"pause"\|"stop"\|"next"\|"prev"\|"vol"\|"mute"\|"unmute"`, `vol?: int 0-100`, `seek?: int` (sec) | `{tp:5, id:6, ms:"vol", vol:30}` |
| SC  | (без полей — активация) | `{tp:5, id:7}` |
| AL  | `al: "arm_home"\|"arm_away"\|"arm_night"\|"disarm"` | `{tp:5, id:8, al:"arm_home"}` |
| SE  | (read-only, CMD не принимается) | — |
| FN  | `s: bool`, `sp?: int 0-100`, `preset?: str`, `osc?: bool`, `dir?: str` | `{tp:5, id:9, s:true, sp:50}` |
| BT  | (без полей — нажатие) | `{tp:5, id:10}` |

**Правила:**
- `rgb` — массив из 3 int `[r, g, b]`, каждый 0-255.
- `ef` — строковый идентификатор эффекта (например, "colorloop", "random").
- `t` (tilt) для CV — угол наклона жалюзи 0-100.
- `th` / `tl` для CL — target temp high/low (для climate с range).
- `seek` для MS — позиция в секундах.

### 8.2. Поля STATUS / PUSH по типам

| Тип | State-поля |
|-----|------------|
| SW  | `v: "on"\|"off"` |
| LT  | `v: "on"\|"off"`, `b?: int 0-100`, `ct?: int`, `rgb?: [r,g,b]`, `ef?: str` |
| CV  | `v: "open"\|"closed"\|"opening"\|"closing"`, `p?: int 0-100`, `t?: int 0-100` |
| CL  | `v: str` (hvac mode), `t?: float`, `tc?: float`, `th?: float`, `tl?: float`, `fan?: str`, `preset?: str`, `swing_h?: str`, `swing_v?: str` |
| LK  | `v: "locked"\|"unlocked"` |
| MS  | `v: "playing"\|"paused"\|"idle"\|"off"\|"buffering"\|"standby"`, `vol?: int 0-100`, `title?: str`, `artist?: str`, `album?: str`, `dur?: int`, `pos?: int`, `muted?: bool` |
| SC  | (нет state — оно одноразовое) |
| AL  | `v: "armed_home"\|"armed_away"\|"armed_night"\|"disarmed"\|"triggered"\|"arming"\|"pending"` |
| SE  | `v: str`, `u?: str` |
| FN  | `v: "on"\|"off"`, `sp?: int 0-100`, `preset?: str`, `osc?: bool`, `dir?: str` |
| BT  | (нет state) |

**Правила:**
- `tc` для CL — текущая температура (current).
- `dur` / `pos` для MS — длительность и позиция трека в секундах.
- `u` для SE — единица измерения (unit_of_measurement), строка.

### 8.3. Нормализация значений

- **Brightness (LT, FN.sp)** — всегда 0-100 в протоколе. HA использует 0-255 — конверсия в `commands.py` и `state_extractor.py`.
- **Sensor value (SE)** — всегда строка. Числа, "unavailable", "unknown" — всё как строка.
- **Color temperature (LT.ct)** — kelvin (int).
- **Volume (MS.vol)** — 0-100 в протоколе. HA использует 0-1.0 (float) — конверсия в `commands.py` и `state_extractor.py`.

---

## 9. Кеширование и синхронизация

### 9.1. Когда App запрашивает конфигурацию

- При первом одобрении (HA сам шлёт всё)
- При смене хеша после PING/PONG-сверки (REQ нужной секции)
- При выходе из offline (App шлёт PING при появлении связи)

### 9.2. Когда HA шлёт инициативный PONG

- При изменении любой секции (m/u/a/d)
- При добавлении/удалении/изменении устройства, области, пользователя
- При смене server_name или version

PONG отправляется всем активным remote'ам.

### 9.3. Когда HA шлёт PUSH

- При любом изменении state зарегистрированного устройства в HA
- Только для устройств из секции `d`
- Всем активным remote'ам (unicast)
- С per-device throttle 500 мс (для SE — max 1/5 сек)

### 9.4. Обработка offline-режима

LXMF имеет три состояния доставки: `OUTBOUND`, `DELIVERED`, `FAILED`. Поведение Rover:

- **OUTBOUND** — нормально, ждём
- **DELIVERED** — успех, ничего делать не нужно
- **FAILED** — логируем, **не повторяем**. Следующий PING/PONG восстановит синхронизацию.

App при выходе из offline сам шлёт PING. HA отвечает PONG. App видит изменения и запрашивает обновление через REQ.

---

## 10. Безопасность

### 10.1. Что обеспечивается транспортом

- **End-to-end шифрование** между HA и каждым телефоном (Reticulum, X25519 + AES-256)
- **Forward Secrecy** для каждого сообщения
- **Невозможность подделать отправителя** (Ed25519-подпись каждого LXMF)
- **Защита от replay** (LXMF message-id + timestamp)

### 10.2. Что обеспечиваем мы

- **Authorization** — каждый входящий CMD сверяется с whitelist'ом identity hash'ей
- **Manual approval** — новые remote'ы не получают доступ автоматически (кроме первого, который становится owner'ом)
- **Лимит активных remote'ов** — 5, чтобы случайно не открыть доступ всем

### 10.3. Чего НЕТ

- **Паролей** — не используются вообще. Авторизация исключительно через Reticulum Identity.
- **Общей соли / PSK** — не нужны.
- **Симметричных ключей канала** — не нужны (E2E через Reticulum).

---

## 11. Структура кодовой базы (HA-интеграция)

```
custom_components/rover/
  __init__.py           # async_setup_entry, RoverRuntimeData, async_unload_entry
  config_flow.py        # одношаговый config flow (генерация identity)
  options_flow.py       # меню: Общие/Устройства/Пользователи/Pending/Конфиг
  const.py              # константы протокола
  registry.py           # Registry: storage, хеши, счётчики short_id/area_id
  codec.py              # msgpack encode/decode для Fields
  commands.py           # build_service_call (CMD → HA service)
  state_extractor.py    # extract_state (HA state → protocol)
  ha_bridge.py          # мост к HA: подписка на state_changed, throttle, вызов сервисов
  rns_transport.py      # инициализация RNS, LXMF router, отправка/приём, graceful shutdown
  handlers.py           # обработка входящих tp=5/6/8/9
  dispatcher.py         # маршрутизация по tp (опционально, можно слить с handlers)
  services.yaml         # HA services (опционально, например test/debug)
  manifest.json
  translations/
```

### 11.1. Что меняется по сравнению с v0.2

Удалены:
- `transport.py` (Meshtastic-специфичный) → заменён на `rns_transport.py`
- `queue.py` (OutQueue, InDedup, Batcher) — функции делегированы LXMF
- Логика фрагментации в `codec.py` — RNS фрагментирует сам

Сохранены (с минорными правками):
- `const.py`, `registry.py`, `commands.py`, `state_extractor.py`, `ha_bridge.py`, `__init__.py`, `config_flow.py`, `options_flow.py`, `handlers.py`, `dispatcher.py`

Добавлены:
- `rns_transport.py` — обёртка над RNS + LXMF Router
- Логика onboarding и pending approval в `options_flow.py`
- Расширение `registry.py` под pending list, кеш хешей, счётчики
- Throttle в `ha_bridge.py`

---

## 12. Константы и лимиты

```python
# Идентичность
IDENTITY_HASH_LEN = 16        # байт
DISPLAY_NAME_MAX_LEN = 32     # символов

# Пользователи
MAX_ACTIVE_REMOTES = 5
MAX_PENDING_REMOTES = 10

# Хеши секций
SECTION_HASH_LEN = 4          # hex-символов (MD5[:2 bytes])
HASH_SERIALIZATION = "canonical_json"  # json.dumps(sort_keys=True, ...)

# Устройства
SHORT_ID_MAX = 0xFFFF         # 65535
SHORT_ID_MIN = 1              # 0 зарезервирован

# Сенсоры
SENSOR_VALUE_AS_STRING = True
SENSOR_PUSH_INTERVAL = 5.0    # сек, max frequency для SE

# Brightness
BRIGHTNESS_RANGE = (0, 100)   # не 0-255

# Volume
VOLUME_RANGE = (0, 100)     # не 0-1.0

# PUSH throttle
PUSH_THROTTLE_MS = 500        # мс, per-device

# Roles
ROLE_OWNER = "owner"
ROLE_REGULAR = "regular"

# QR
QR_FORMAT_VERSION = 1

# Зависимости
REQUIREMENTS = ["rns>=1.2.0", "lxmf>=0.9.6"]
```

---

## 13. Версионирование

- **SemVer.** Текущая версия SPEC: `0.3.0`.
- **Bumping rules:**
  - Patch (0.3.x) — баг-фиксы, уточнения формулировок
  - Minor (0.x.0) — новые опциональные поля, новые tp, новые типы устройств (backwards-compatible)
  - Major (x.0.0) — breaking changes (новый формат сообщений, удаление полей, изменение семантики)
- **Совместимость HA ↔ App:** оба должны поддерживать одинаковый major. Minor mismatch — App работает с подмножеством фичей.

---

## 14. Что осталось вне SPEC (бэклог)

- Per-remote device whitelists (индивидуальные списки устройств)
- LXMF Propagation Nodes для надёжного store-and-forward через mesh
- Дельта-обновления конфигурации (вместо отправки целой секции)
- Дополнительное шифрование payload поверх LXMF (если потребуется паранойя)
- Передача больших данных (камеры, файлы) через RNS Link
- Алерты (управление на стороне App, см. DECISIONS 016)
- Onboarding через файл-импорт identity (когда QR недоступен)
- Blacklist отозванных identity (DECISIONS Q2)
- Гостевой режим без регистрации (DECISIONS Q4)

---

## 15. Глоссарий

- **RNS** — Reticulum Network Stack, низкоуровневый сетевой стек.
- **LXMF** — Lightweight eXtensible Message Format, протокол сообщений поверх RNS.
- **Identity** — пара криптоключей в RNS (Ed25519 + X25519).
- **Destination hash** — 16-байтовый идентификатор адресата.
- **RNode** — открытое LoRa-устройство, рекомендуемое для Reticulum (можно прошить из SX127x/SX126x/SX1280/LR1121).
- **Propagation Node** — узел Reticulum, хранящий сообщения для оффлайн-получателей.
- **Remote** — Rover-App, зарегистрированный на HA (синоним «пульт»).
- **Owner** — первый зарегистрированный remote, имеет admin-права.
- **Regular** — обычный remote, без admin-прав.
- **short_id** — 2-байтовый идентификатор устройства (0-65535), используется в hot-path сообщениях.
- **Секция** — m / u / a / d, часть конфигурации с собственным хешем.
- **Canonical JSON** — сериализация с `sort_keys=True`, `ensure_ascii=False`, `separators=(',',':')`.