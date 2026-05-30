# Rover / app — Agent Instructions

Android-приложение. Подключается по BLE к Meshtastic-устройству, общается с шлюзом (Rover back) поверх LoRa.

## Repository
https://github.com/BotoVed/Rover (монорепо)
Эта папка: `app/`
Локальный путь: `tmp/rover/app/`

## Обязательное чтение перед работой
1. [`../SPEC.md`](../SPEC.md) — спецификация продукта (что строим).
2. [`../DECISIONS.md`](../DECISIONS.md) — журнал архитектурных решений (как и почему).
3. Этот файл — операционные инструкции.

При расхождении приоритет: SPEC → DECISIONS → AGENT.

## Environment
| | |
|---|---|
| OS | Ubuntu 24 |
| Java | openjdk-21 `/usr/lib/jvm/java-21-openjdk-amd64` |
| Android SDK | `~/android-sdk` (SDK 34, build-tools 34.0.0) |
| Gradle | `/tmp/gradle-8.6/bin/gradle` — НЕ системный gradle |
| ADB | `~/android-sdk/platform-tools/adb` |
| Project | `tmp/rover/app/` |
| Package | `com.rover.app` |

## Workflow
```
read AGENT.md + ../SPEC.md + ../DECISIONS.md
→ write/change code
→ build:   export ANDROID_HOME=~/android-sdk && /tmp/gradle-8.6/bin/gradle assembleDebug --no-daemon
→ install: ~/android-sdk/platform-tools/adb install -r app/build/outputs/apk/debug/app-debug.apk
→ logs:    ~/android-sdk/platform-tools/adb logcat -s "BleService" "Transport" "Queue" "Dispatcher" "MainActivity"
→ commit + push (patch x.y.1)
→ test → fix → patch x.y.2, x.y.3 …
→ итоговый тест → commit + push (minor x.(y+1).0)
→ git tag app-x.(y+1).0
→ обновить AGENT.md (после минора) и DECISIONS.md (если меняли логику)
```

```bash
# commit template
git add -A && git commit -m "app vX.Y.Z — description" && git push origin main

# tag
git tag app-X.Y.Z && git push origin app-X.Y.Z
```

APK прикрепляется к GitHub Release при минорных релизах (см. ниже).

## Project Structure
```
app/
├── README.md
├── AGENT.md                            — этот файл
├── build.gradle.kts
├── settings.gradle.kts
└── app/
    ├── build.gradle.kts
    └── src/main/
        ├── AndroidManifest.xml
        ├── proto/mesh.proto            — Meshtastic protobuf
        └── java/com/rover/app/
            ├── App.kt
            ├── transport/
            │   ├── Meshtastic.kt       — BLE-связь с Meshtastic-нодой
            │   ├── Codec.kt            — MessagePack, фрагментация tp=7
            │   └── Queue.kt            — очередь, дедуп, повторы, пачки
            ├── domain/
            │   ├── Registry.kt         — локальная копия маппинга, cfgh
            │   ├── Dispatcher.kt       — маршрутизация tp → handler
            │   └── Handlers.kt         — on_push, on_status, on_config
            ├── state/
            │   └── AppState.kt         — глобальный state (Flow)
            ├── ble/
            │   ├── BleService.kt       — Foreground Service, удерживает BLE в фоне
            │   └── BleScanner.kt       — сканирование BLE-устройств
            ├── ui/
            │   ├── MainActivity.kt
            │   ├── DevicesScreen.kt
            │   ├── DeviceCard.kt
            │   ├── SettingsScreen.kt
            │   └── LogScreen.kt
            └── util/
                └── Logger.kt           — кольцевой буфер логов
```

## Meshtastic BLE API
Meshtastic использует собственный BLE API, **не** Nordic UART Service.

```
Service:   6ba1b218-15a8-461f-9fa8-5dcae273eafd
ToRadio:   f75c76d2-129e-4dad-a1dd-7866124401e7  (write)
FromRadio: 2c55e69e-4993-11ed-b878-0242ac120002  (read)
FromNum:   ed9da18c-a800-4f66-a670-aa7547e34453  (notify)
```

### Handshake sequence
```
1. connect() + requestMTU(512) → actual MTU=247
2. enableNotifications(fromNum)
3. write(toRadio, [0x18, 0x00])   ← startConfig (want_config_id=0)
4. poll fromRadio until empty
5. receive CONFIG_COMPLETE_ID (field 6) → BleState.Ready
6. on fromNum notify → read fromRadio in loop
```

### Sending packets
```
to        = 0xFFFFFFFF   ← broadcast (only mode supported)
channel   = 0            ← приватный канал (на MVP допустим LongFast, key=AQ==)
portnum   = 256          ← PRIVATE_APP
hop_limit = из настроек, по умолчанию 0
```

Direct message (to=node_num) **не работает** — Meshtastic 2.x использует PKC-шифрование для DM, ключей у нас нет. Только broadcast.

### Protobuf (mesh.proto)
```protobuf
message Data       { uint32 portnum=1; bytes payload=2; }
message MeshPacket { fixed32 from=1; fixed32 to=2; Data decoded=3; fixed32 id=9; ... }
message FromRadio  { oneof { MeshPacket packet=2; uint32 config_complete_id=6; ... } }
message ToRadio    { oneof { MeshPacket packet=1; uint32 want_config_id=3; } }
```
⚠️ Использовать **fixed32** для `from` / `to` / `id` — не uint32, иначе portnum=0 при парсинге.

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
MessagePack может закодировать число как Int, Long или UInt в зависимости от размера. **Декодер обязан принимать любой из этих типов** для всех числовых полей.

### Идентификация устройств
`short_id` — 2-байтовый Int (16 бит). Передаётся как число, не строка. Маппинг `short_id → entity_id, friendly_name, type, area` приходит в составе CONFIG.

### Очередь
- Ключ исходящей очереди = `short_id` устройства.
- Новая команда для того же устройства затирает старую, счётчик повторов сбрасывается.
- Первая отправка — немедленно. Повторы — каждые N секунд (настройка, дефолт 15).
- Максимум повторов — настройка, дефолт 5.
- Сообщения в пачке — до 200 байт суммарно.
- Не помещающиеся в пакет — фрагментируются (tp=7).
- Дедуп входящих: обработанные сообщения хранятся 15 минут.

### Жизненный цикл команды
1. Пользователь меняет значение → UI отображает устройство серым (неподтверждённым).
2. CMD кладётся в очередь.
3. Бэк выполняет → шлёт PUSH broadcast.
4. Приложение получает PUSH → снимает серый, применяет состояние.
5. Если PUSH не пришёл за `период × попыток` — устройство остаётся серым. Ошибка пользователю **не показывается**.

## Foreground Service Architecture
```
BleService (LifecycleService — always alive, START_STICKY)
    ├── Meshtastic (BLE-связь)
    ├── BleScanner
    ├── Transport (отправка/приём через Codec)
    ├── Queue (цикл обработки)
    ├── Dispatcher (маршрутизация входящих)
    ├── pingLoop — каждые 2 минуты в состоянии Ready
    └── updateNotification() — статус в шторке уведомлений

MainActivity
    ├── startForegroundService() + bindService()
    ├── collect AppState (Flow)
    └── onStop(): unbind, но НЕ stopService
```

```xml
<!-- AndroidManifest.xml -->
FOREGROUND_SERVICE, FOREGROUND_SERVICE_CONNECTED_DEVICE, POST_NOTIFICATIONS

<service android:name=".ble.BleService"
         android:foregroundServiceType="connectedDevice"
         android:exported="false"/>
```

## Dependencies
```
AGP: 8.4.0 | Kotlin: 1.9.22 | JVM target: 21 | Gradle: 8.6
nordic ble: 2.7.4 + ble-ktx: 2.7.4
msgpack-core: 0.9.8
protobuf-kotlin-lite: 3.25.1
coroutines-android: 1.7.3
lifecycle-service: 2.7.0 | lifecycle-runtime-ktx: 2.7.0
appcompat: 1.6.1 | material: 1.11.0
```

## Critical Patterns
- Использовать `LifecycleService` для BleService (не plain Service) — нужно для корутин.
- Вызывать `setGattCallbacks(this)` **до** `connect()`.
- Реализовать интерфейс `BleManagerCallbacks` — не переопределять методы напрямую.
- `BleState.Ready` устанавливать на `CONFIG_COMPLETE_ID`, не на пустом буфере.
- Только broadcast: `to=0xFFFFFFFF`, `channel=0`.
- `fixed32` для `from` / `to` / `id` в MeshPacket — иначе portnum парсится как 0.
- Числовые поля MessagePack принимать как Int **или** Long.
- Ключ очереди = `short_id`, новая команда затирает старую.
- Дедуп входящих по уникальному ID сообщения, окно 15 минут.

## Конфигурация подключения
Параметры (адрес шлюза, имя/PSK Meshtastic-канала, hop limit, период повторов, число попыток) хранятся в `SharedPreferences("rover")`. На MVP вводятся вручную в SettingsScreen. После MVP — импорт через QR.

## Соглашения по коду
- Логика транспорта **не знает** про Meshtastic-протобуфы — только `ByteArray ↔ Meshtastic.kt`.
- Логика очереди **не знает** про MessagePack — только `OutPacket ↔ Codec.kt`.
- Обработчики **не знают** про транспорт — только `dispatcher → handler → AppState/Queue`.
- Один файл = одна ответственность.
- Состояние устройств — только в `Registry` / `AppState`. Никаких локальных копий в UI.

## Релизы
При каждом минорном повышении версии:
1. `git tag app-X.Y.0`
2. `git push origin app-X.Y.0`
3. GitHub Release с прикреплённым APK (`app-release.apk`).

## Что обновлять после изменений
- Изменили поведение, поля пакета, тип устройства → **../SPEC.md** + **../DECISIONS.md** (синхронно).
- Изменили команду билда, структуру проекта, добавили зависимость, минорное повышение версии → **AGENT.md**.
