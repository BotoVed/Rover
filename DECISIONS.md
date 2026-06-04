# Rover — Architecture Decisions Log

**Версия:** 0.3.0
**Формат:** append-only лог решений. Каждая запись имеет номер, дату не указываем (порядок номеров отражает хронологию).

При значительных изменениях архитектуры новые записи **могут отменять** старые. Отменённые помечены как **SUPERSEDED** с ссылкой на заменяющую запись.

---

## Часть 1: Перенесённые решения из v0.2 (Meshtastic-эра)

Эти решения остаются актуальными в Reticulum-архитектуре с минорными уточнениями.

### 016. Алерты — на стороне приложения
Бэк не обрабатывает алерты. Это функционал Rover-App. Бэк просто шлёт PUSH с состояниями, App сам решает что важно показать как уведомление.

### 028. commands.py и state_extractor.py как чистые функции
Логика сборки HA service call и извлечения state из HA-объекта живёт в отдельных модулях с чистыми функциями. Тестируются без моков HA. Не зависят от транспорта.

### 029-035. Множественные хеши секций
Вместо одного `cfgh` — 4 хеша по 4 hex-символа: `m` (meta), `u` (users), `a` (areas), `d` (devices). Это позволяет точечно обновлять только изменившиеся секции.

### 030. Brightness 0-100
В протоколе яркость всегда нормализована в диапазон 0-100 (не 0-255 как в HA). Конверсия — в `commands.py` (при CMD) и `state_extractor.py` (при PUSH/STATUS). Это упрощает UI на App: единая шкала, не нужно делить на 2.55.

### 031. Alarm command — фиксированный список
Команда alarm-панели принимает только 4 значения: `arm_home`, `arm_away`, `arm_night`, `disarm`. Любое другое — ошибка валидации.

### 032. Бэк = источник истины
HA — единственный источник состояний и конфигурации. App не хранит entity_id, не строит свою картину мира. Только отображалка и пульт. Если соединение прервалось — App показывает «связь потеряна», но не пытается угадывать состояние.

Следствие: `entity_id` НЕ передаётся в App. Используется только `short_id` (2 байта). Маппинг ведётся на бэке.

### 033. Sensor value — всегда строка
Значение сенсора (поле `v` для типа SE) передаётся как строка, не как Double. Это даёт гибкость: можно отдать «25.5», «on/off», «unavailable», «unknown» — одним типом данных. App сам решает как форматировать.

### 034. Современные паттерны HA
Используем `config_flow`, `async_setup_entry`, `runtime_data` (вместо `hass.data[DOMAIN]`), `executor_job` для блокирующих операций. Никаких устаревших API.

### 037. Имена секций m / u / a / d
Короткие коды для секций. На бэке всегда используются эти имена. `mpg` (страница) — удалён вместе с пагинацией (см. 053).

### 038. Инициативный PONG
Бэк отправляет PONG всем активным remote'ам **без запроса**, когда меняется хеш любой секции. Это позволяет App'ам узнавать об изменениях быстро без polling'а.

### 039. PING / PONG — чистый обмен хешами
PING / PONG не вызывают никаких side-effect'ов на бэке (не запускают service call, не пишут в реестр). Это **только** обмен хешами секций. Если хеши совпадают — ничего не происходит. Если различаются — App инициирует REQ.

### 044. HACS-совместимая структура
Код интеграции живёт в `custom_components/rover/` в корне репозитория. Релизы — через GitHub Releases с asset'ом `rover.zip`. ZIP собирается локально.

---

## Часть 2: Отменённые решения (v0.2 → v0.3 миграция)

### 040. ~~want_ack=true для ВСЕХ пакетов~~ — **SUPERSEDED by 057**
Было: каждый Meshtastic-пакет отправляется с want_ack=true, ACK подтверждает доставку, NAK/timeout вызывает retry. Очередь с фазами active/awaiting_ack/suspended.

Отменено: LXMF имеет встроенный delivery state (`OUTBOUND` / `DELIVERED` / `FAILED`). Никаких ACK на уровне приложения не нужно.

### 042. ~~Общая соль для паролей через секцию meta~~ — **SUPERSEDED by 045**
Было: пароли пользователей хешировались с общей солью, передаваемой через секцию meta. SHA-256.

Отменено: пароли удалены из протокола полностью. Авторизация через RNS Identity (Ed25519/X25519). Идентичность нельзя подделать.

### 043. ~~OptionsFlow меню: Общие / Устройства / Пользователи / Конфиг~~ — **AMENDED by 050**
Сохранено как идея (меню в options_flow), но содержимое меняется: добавляется раздел Pending (запросы на регистрацию), раздел Конфиг упрощается (нет паролей, есть QR с identity).

### 036. ~~tp=8 REQ как замена cfg=1/cfg=2~~ — **сохранено, но переосмыслено**
Сам тип tp=8 остаётся. Меняется только: нет страниц (`page`). REQ запрашивает целую секцию.

---

## Часть 3: Решения Reticulum-эры (v0.3+)

### 045. Reticulum / LXMF как единственный транспорт
**Решение:** Полностью отказываемся от Meshtastic. Транспорт — Reticulum Network Stack + LXMF.

**Причины:**
- Meshtastic — это firmware с протоколом сообщений, а не сетевой стек. Использовать его для приложения уровня умного дома — натягивать сову.
- Reticulum — полноценный networking stack, написан на Python, нативно поддерживает identity-based addressing, end-to-end шифрование, store-and-forward, мульти-интерфейс.
- LXMF поверх RNS даёт нам готовую систему сообщений с подтверждением доставки. Не нужно писать свои очереди, ACK, retry, fragment.
- 128 hops max vs 7 у Meshtastic. MTU 500 байт vs 200.
- Reticulum работает над любым медиа: RNode (LoRa), TCP/IP, WiFi, serial — одним и тем же кодом.

**Цена:**
- Меньше распространён в RV-сообществе чем Meshtastic.
- Нужно другое железо — RNode (можно прошить существующие LoRa-платы SX127x/SX126x/SX1280/LR1121, в т.ч. бывшие Meshtastic-устройства).
- На Android — используем Columba (нативный Kotlin LXMF клиент) как основу.

### 046. RNS Identity вместо паролей
**Решение:** Аутентификация и авторизация — исключительно через RNS Identity.

**Следствия:**
- HA-сервер имеет одну Identity (сгенерирована при первом запуске).
- Каждый телефон имеет свою Identity.
- Сообщения подписаны Ed25519. Подделать отправителя невозможно.
- Списки доступа = списки одобренных identity hash'ей.
- Пароли, соли, PSK — удалены из протокола.

**Что было раньше (v0.2):** users-секция содержала login/password пары. Пароли хешировались с общей солью. Это самопальная схема была вынужденной из-за Meshtastic, который не имеет понятия идентичности.

### 047. Онбординг через QR + pending approval
**Решение:** Двух-этапный онбординг:

1. Сканирование QR с identity сервера → App знает куда слать.
2. App отправляет REGISTER → HA добавляет в pending → owner одобряет через HA UI.

**Исключение:** если активных remote'ов 0, первый зарегистрировавшийся **автоматически становится owner'ом** без pending. Это решает проблему «куриного яйца» — кто-то должен иметь право одобрять остальных.

**Альтернатива (отклонено):** мгновенный approve при первом QR-сканировании. Опасно: если телефон угнан или identity скомпрометирована, злоумышленник может зарегистрироваться. Pending дешевле и безопаснее.

### 048. Один общий список устройств для всех remote'ов
**Решение:** Все одобренные remote'ы видят одинаковый набор устройств. Per-remote whitelist'ы (индивидуальные списки) — в бэклоге.

**Причина:** Упрощение MVP. Реализация per-remote view значительно усложняет:
- Секции `d` и `a` становятся per-remote (разные хеши для разных пультов)
- Логика PUSH усложняется (фильтрация по правам)
- HA UI разрастается (управление whitelist'ом для каждого remote'а)

**Когда добавится:** Когда базовый цикл (CMD/PUSH/CONFIG/PING-PONG) стабилизируется. Расширение совместимо назад: добавится опциональное поле `visible_to: [hash, hash, ...]` в записях устройств.

### 049. Роли: owner и regular
**Решение:** Только две роли в v0.3.

- **owner** — первый зарегистрированный. Видит все устройства. Может approve / revoke других remote'ов. Может редактировать конфигурацию устройств.
- **regular** — все остальные одобренные. Видят все устройства. Не могут управлять другими remote'ами.

**Управление whitelist'ом (когда появится):** будет через HA UI, не через App. App только показывает доступные ему устройства.

### 050. Максимум 5 активных remote'ов
**Решение:** Лимит активных одобренных remote'ов — 5. Pending — отдельная очередь, лимит 10.

**Причина:**
- PUSH на каждый remote → unicast loop. При 5 устройствах × 5 remote'ов = 25 пакетов на каждое изменение состояния. На LoRa с 5-10 пакетами/секунду — это уже нагрузка.
- Семейный сценарий: 1-5 человек в RV. Больше — редкость.
- В будущем при необходимости — LXMF Propagation Node решит проблему масштабирования.

### 051. tp=9 REGISTER как отдельный тип сообщения
**Решение:** Регистрация нового remote'а — через явный тип сообщения `tp=9`.

```
{tp: 9, name: "Иван", ver: "0.3.0"}
```

Поле `ver` — опционально, версия App для будущей совместимости.

**Альтернатива (отклонено):** использовать LXMF Content или Title для имени, без специального tp. Отклонено: ломает единообразие — везде используем Fields с tp.

### 052. Удалён tp=7 FRAGMENT
**Решение:** Фрагментация делегируется Reticulum.

В Reticulum / LXMF большие сообщения автоматически разбиваются на пакеты и собираются на стороне получателя. Нам не нужно реализовывать fragment_id, fragment_total, FragmentBuffer.

**Следствие:** `codec.py` сильно упрощается — остаётся только msgpack encode/decode.

### 053. Удалён cmid и пагинация
**Решение:**
- Поле `cmid` (command id для дедупликации) — удалено. LXMF дедуплицирует по message-id (SHA-256 от Destination + Source + Payload).
- Поле `mpg` (page) и пагинация в CONFIG — удалены. Reticulum обрабатывает большие сообщения нативно.

### 054. Удалена общая соль `meta.salt`
**Решение:** Поле `salt` в секции `m` (meta) удалено. Никаких паролей больше нет, соль не нужна.

### 055. Никаких retry на стороне приложения
**Решение:** Если LXMF доставка завершилась в состоянии FAILED — **ничего не делаем**. Не повторяем, не накапливаем в очереди.

**Восстановление синхронизации:** PING/PONG между App и HA при следующем contact'е автоматически выявит расхождение хешей. App сам запросит обновление через REQ.

**Причина:** Любой retry-механизм с накапливанием — это новые баги (запылившаяся очередь, повторная доставка устаревших команд, race conditions). LXMF retry на своём уровне уже делает достаточно.

### 056. Multi-interface Reticulum — на уровне конфигурации, не кода
**Решение:** Если пользователь хочет использовать несколько физических интерфейсов (например, RNode + TCP + WiFi), это настраивается в `~/.reticulum/config`. Наш код **не знает** какие интерфейсы активны — работает только с абстракциями RNS (Destination, Link, Packet, LXMF Router).

**Польза:** В сценарии RV — телефон дома говорит с HA через локальный WiFi (быстро), а в дороге — через LoRa RNode (медленно но работает). Одна и та же Identity, прозрачное переключение.

### 057. Очередь и ACK — делегированы LXMF
**Решение:** Удаляем `queue.py` целиком (OutQueue, InDedup, Batcher). Удаляем логику ACK / retry / timeout.

**Что вместо:** LXMF Router предоставляет `lxm.set_delivery_callback(...)` и состояния `OUTBOUND` / `DELIVERED` / `FAILED`. Этого достаточно.

**Дедупликация входящих:** LXMF дедуплицирует по message-id автоматически.

### 058. Android: Rover-App на базе Columba
**Решение:** Rover-App строится на основе [Columba](https://github.com/torlando-tech/columba) — нативное Android-приложение на Kotlin с интегрированным Reticulum-стеком и LXMF.

**Почему не альтернативы:**
- **Sideband (Markqvist)** — отличное приложение, но написано на Python через Kivy. Тяжёлое, медленное на Android, не нативный UI.
- **LXMF-rs (Rust)** — через JNI, потенциально быстро, но требует своей реализации UI с нуля. Долго.
- **Своя реализация Reticulum на Kotlin** — слишком большой объём работы.

**Columba даёт:**
- Нативный Kotlin Reticulum stack (рабочий)
- LXMF messaging (рабочий)
- BLE-Reticulum (нативная Android реализация для связи с RNode через Bluetooth)
- QR-сканер и генератор для шеринга identity
- Управление несколькими identity, импорт/экспорт
- Material Design 3

**Что добавляем в Rover-App:**
- UI для устройств (плитки SW/LT/CV/CL/...)
- UI для онбординга (сканирование HA QR, отправка REGISTER)
- Локальный кеш конфигурации с проверкой хешей
- UI карточек по типам устройств
- Алерты (на основе PUSH-уведомлений) — см. DECISIONS 016

### 059. Версионирование SPEC и совместимость
**Решение:** SPEC версионируется по SemVer. HA и App обязаны поддерживать одинаковый major. Minor mismatch — деградация фичей, не падение.

Текущий major: 0. Это означает что мы в pre-1.0 фазе и допускаем breaking changes между минорными версиями при необходимости. Версия 1.0.0 будет означать стабилизацию протокола.

### 060. Структура репозиториев и зависимости
**Решение:**

- `BotoVed/Rover` — главный, содержит SPEC, DECISIONS, и `custom_components/rover/` (HA-интеграция). Версионирование `back-x.y.z` (или просто `x.y.z` для HACS).
- `BotoVed/Rover-App` — Android-приложение. Форк или зависимость от Columba (решить отдельно). Версионирование `app-x.y.z`.
- `BotoVed/Rover-Card` — Lovelace-карточка. Версионирование `card-x.y.z`.

Кросс-совместимость по major'у SPEC. Каждый компонент в `manifest.json` / `package.json` указывает поддерживаемый major SPEC.

**Зависимости HA-интеграции:** `rns>=1.2.0`, `lxmf>=0.9.6` (в `manifest.json`).

### 061. Лицензия и монетизация
**Решение:** GPL v3 для всех трёх репозиториев. Монетизация — GitHub Sponsors на профиле BotoVed.

GPL гарантирует что любые форки или коммерческие использования должны оставаться open source. Это соответствует духу Reticulum (тоже open, без vendor lock-in).

### 062. Registry storage + кеш хешей
**Решение:** Данные registry (users, devices, areas, pending, meta) хранятся в `homeassistant.helpers.storage.Store`, путь `<config>/.storage/rover_registry.json`.

Хеши секций (`_hash_m`, `_hash_u`, `_hash_a`, `_hash_d`) кешируются в registry и пересчитываются **только при мутации данных**. Хеш — дорогая функция (MD5 от канонической сериализации), не вычисляем её на каждом чтении.

### 063. RNS Identity в директории интеграции
**Решение:** Identity HA-сервера и `config` Reticulum живут внутри `<config>/custom_components/rover/.reticulum/`. Путь передаётся явно при инициализации: `RNS.Reticulum(configdir=path)`.

Это гарантирует, что при бэкапе HA через Snapshot бэкапятся и identity, и конфигурация сети, и registry.

### 064. short_id — последовательный счётчик
**Решение:** `short_id` назначается последовательно от `1`. Счётчик хранится в registry (`_next_short_id`). При удалении устройства ID **не reuse** (чтобы не сломать кеш App).

При переполнении 65535 — wrap-around: перебираем от `1` до первого свободного числа. `0` зарезервирован как «не назначен».

### 065. Добавление устройств через Options Flow
**Решение:** В `options_flow` раздел «Устройства» показывает picker со всеми HA entity, фильтрованными по поддерживаемым domain (switch, light, cover, climate, lock, media_player, scene, alarm_control_panel, sensor, binary_sensor, fan, button).

Пользователь галочками включает entity в Rover. При включении:
- `short_id` = следующий счётчик
- `name` = `friendly_name` из HA (редактируемо в Rover UI)
- `type` = автоопределение по domain (таблица SPEC §8)
- `area_id` = мапится на Rover area (см. 066)
- `entity_id` и `type` — read-only в Rover UI

### 066. Rover Area = копия HA Area
**Решение:** Rover area — это копия HA area на момент добавления устройства, не прямая ссылка. При импорте entity: если у неё есть `area_id` в HA entity registry — создаётся Rover area с автоинкрементным `id` (отдельный счётчик) и именем из HA area registry. Если такая area уже существует в Rover — используется существующий `id`.

**Пользователь НЕ может переименовать Rover area** — иначе возникает путаница между HA и Rover. Переименование area делается в HA, затем переимпортируется через Options Flow (кнопка «Обновить из HA»).

### 067. Per-device throttle 500 мс на PUSH
**Решение:** В `ha_bridge.py` добавляется per-device throttle 500 мс на PUSH. Если state меняется чаще — предыдущее значение в throttle-окне **затирается**, отправляется только последнее после задержки.

Для сенсоров (SE) — дополнительно max frequency 1 PUSH / 5 сек.

Это не нарушает DECISIONS 057: throttle — фильтр на источнике событий, а не retry/queue на транспорте.

### 068. Каноническая сериализация для хеша секций
**Решение:** Для вычисления хеша: сериализуем секцию в **canonical JSON** (`json.dumps(data, sort_keys=True, ensure_ascii=False, separators=(',',':'))`) → UTF-8 bytes → MD5 → первые 2 байта (4 hex-символа).

Для передачи по сети используем msgpack (компактнее). Хеш считается от логической структуры, не от бинарного представления — это гарантирует совпадение хешей на Python и Kotlin.

### 069. Graceful shutdown при unload/reload
**Решение:** В `async_unload_entry` вызывается `rover_runtime_data.transport.shutdown()`: закрыть LXMF router, вызвать `rns.reticulum.exit_handler()`, убить executor job.

При reload: остановить → подождать 1 сек → стартовать заново с той же identity. После старта отправить инициативный PONG всем активным remote'ам (чтобы App узнали, что HA снова online).

### 070. Формат QR-кода
**Решение:** QR содержит JSON-текст:
```json
{"rvr": {"fmt": 1, "dst": "a1b2c3d4...", "nm": "Дом на колёсах"}}
```
- `fmt` — версия формата QR для будущей совместимости
- `dst` — Reticulum destination hash в hex (32 символа)
- `nm` — display name сервера

App сканирует → извлекает `dst` → сохраняет как адрес сервера → шлёт REGISTER.

### 071. Версия App в REGISTER
**Решение:** В `tp=9 REGISTER` добавлено опциональное поле `ver`: `{tp: 9, name: "...", ver: "0.3.0"}`. HA сохраняет версию в registry (для информации и будущей совместимости), но не использует для логики в v0.3.0.

### 072. Полные поля для всех типов устройств
**Решение:** Сразу закладываем полный набор полей для каждого типа устройств, без деления на MVP/бэклог. Подробные таблицы — в SPEC §8.

Ключевое правило: новые опциональные поля добавляются без breaking change. App игнорирует неизвестные поля.

### 073. Зависимости в manifest.json
**Решение:** `manifest.json` содержит `"requirements": ["rns>=1.2.0", "lxmf>=0.9.6"]`. Перед релизом проверяем совместимость с Python 3.12 (core 2026.4.3).

### 074. Config Flow — одношаговый
**Решение:** Config flow состоит из одного шага, без полей ввода. При нажатии «Добавить интеграцию Rover»:
1. Генерируется RNS Identity (через executor job, ~1–2 сек).
2. Создаётся default `server_name = "Rover Hub"`.
3. Создаётся config entry с `title="Rover Hub"`.
4. Показывается success-сообщение с инструкцией открыть Options Flow для добавления устройств и просмотра QR-кода.

Все данные (users, devices, areas) живут в registry storage, не в `config_entry.data`.

### 075. Options Flow — структура меню
**Решение:** Options Flow предоставляет меню с разделами:
- **Общие:** `server_name` (text).
- **Устройства:** таблица (entity_id, short_id, name, type, area, enabled). Entity picker для добавления из HA. Редактирование name/area/enabled. Кнопка «Обновить из HA» (синхронизирует friendly_name и area_id).
- **Пользователи:** список активных (hash, name, role, кнопка «Отозвать»).
- **Pending:** список запросов (hash, name, requested_at, кнопки «Одобрить» / «Отклонить»). Лимит 10.
- **Конфиг:** QR-код (SVG/PNG), кнопка «Экспорт identity» (скачать файлы из `.reticulum/` для backup/migration).

### 079. Path discovery перед отправкой
**Решение:** Перед отправкой LXMessage в `rns_transport.send()` нужно:
1. Вызвать `RNS.Identity.recall(remote_hash)` — получить identity получателя.
2. Если identity не найдена — вызвать `RNS.Transport.request_path(remote_hash)`, подождать 3-5 секунд, повторить попытку recall.
3. Если после 3 попыток identity всё ещё неизвестна — логировать FAILED, не повторять. Следующий PING/PONG восстановит синхронизацию (см. 055).

**Причина:** `LXMF.LXMessage` требует `RNS.Destination` объект, который строится только при наличии Identity получателя. Без identity Reticulum не может зашифровать сообщение.

**Что НЕ делать:** не передавать bytes hash в качестве destination (это известная распространённая ошибка). Не накапливать сообщения в долгой очереди при отсутствии path — это нарушит DECISIONS 055.

---


## Часть 5: Логирование и инструменты тестирования

### 076. Иерархия логгеров и trace ID

**Решение:** Логирование разбито на 5 иерархических логгеров:

```
custom_components.rover          — корневой (codec, commands, state_extractor)
custom_components.rover.rns      — Reticulum внутренности (RNS.init, router)
custom_components.rover.reg      — Registry (мутации, хеши, счётчики)
custom_components.rover.trn      — Transport (LXMF inbound/outbound/delivery/failed)
custom_components.rover.hab      — HA Bridge (state change, throttle, service calls)
custom_components.rover.hnd      — Handlers (dispatch, tp=5/6/8/9)
```

**Trace ID:** Каждое LXMF-сообщение получает trace ID — первые 8 hex-символов от `LXMessage.hash`. Он приклеивается ко всем логам внутри одного жизненного цикла сообщения через `extra={"rover_trace": trace}`.

**Уровни по умолчанию (production):**
- `INFO` — корневой, registry, handlers (события безопасности и мутации)
- `DEBUG` — transport, HA bridge (объёмный трафик)
- `WARNING` — rns (Reticulum сам шумит на DEBUG)

**Формат:** `%(asctime)s %(levelname)-8s %(name)-25s %(message)s`

**Что логировать на каждом уровне:**
- `INFO`: старт/стоп, мутации registry, REGISTER (все), CMD (все), service calls, delivery failed
- `DEBUG`: inbound/outbound поля (keys only, не values), throttle decisions, PING/PONG/REQ/CONFIG, hash cache
- `WARNING`: отклонённые авторизацией CMD, failed delivery, переполненные очереди, неизвестные типы устройств
- `ERROR`: исключения в encode/decode, service call errors, counter overflow

### 077. Тестовые сервисы Home Assistant

Для отладки без Android-устройства и без реальной сети предоставляются 4 сервиса.

#### `rover.set_loglevel`
Временно меняет уровень логирования на заданный интервал времени, затем возвращает к production-умолчаниям.

Поля:
- `level`: `debug` | `info` | `warning` | `error`
- `duration_minutes`: int, default 30

#### `rover.send_test_message`
Отправляет **реальное** LXMF-сообщение через Reticulum stack. Используется для проверки connectivity и delivery callback'ов.

Поля:
- `destination_hash`: hex-строка (32 символа) или `"self"` для loopback. При `"self"` сообщение уходит через RNS и возвращается обратно через inbound callback (если RNS доставляет loopback).
- `tp`: int (2–9), тип сообщения по SPEC.
- `payload`: JSON-объект, содержимое fields.

**Примеры использования (Developer Tools → Services):**

1. **Эмуляция PING от remote:**
   ```yaml
   service: rover.send_test_message
   data:
     destination_hash: "self"
     tp: 6
     payload:
       h:
         m: "0000"
         u: "0000"
         a: "0000"
         d: "0000"
   ```
   Ожидаемый результат: в логах `IN [trace] tp=6` → `PONG [trace]` → `OUT [trace] tp=6`.

2. **Тест REGISTER:**
   ```yaml
   service: rover.send_test_message
   data:
     destination_hash: "self"
     tp: 9
     payload:
       name: "TestPhone"
       ver: "0.3.0"
   ```
   Ожидаемый результат: `REGISTER [trace] from=dead…` → pending queue +1 (или auto-approve если active==0).

3. **Тест CMD на устройство id=1:**
   ```yaml
   service: rover.send_test_message
   data:
     destination_hash: "self"
     tp: 5
     payload:
       id: 1
       s: true
   ```
   Ожидаемый результат: `CMD [trace] id=1 entity=switch.xxx → switch.turn_on`. Если source не в users — `CMD reject`.

**Ограничение:** при `destination_hash != "self"` требуется реальный путь в Reticulum (remote должен быть в сети). Этот сервис **не обходит** authorization — inbound callback проверяет `source_hash` как обычно.

#### `rover.simulate_inbound`
Впрыскивает сообщение напрямую в `dispatcher.handle_message`, **минуя** Reticulum transport. Используется для unit-тестирования handlers без запущенного RNS и без реального remote.

Поля:
- `source_hash`: hex-строка (32 символа). Можно указать любой hash — он будет подставлен как `message.source_hash`.
- `tp`: int (2–9)
- `payload`: JSON-объект
- `authorized`: bool, default `false`. Если `true`, указанный `source_hash` временно добавляется в `registry.users` с ролью `regular` на время обработки этого сообщения (и только для него).

**Пример — тест CMD без регистрации remote:**
```yaml
service: rover.simulate_inbound
data:
  source_hash: "aabbccdd11223344556677889900aabb"
  tp: 5
  payload:
    id: 1
    s: true
  authorized: true
```
Ожидаемый результат: `CMD [trace] id=1 …` → service call выполняется. При `authorized: false` ожидаем `CMD reject`.

**Важно:** `simulate_inbound` не создаёт реального LXMF `LXMessage`, поэтому delivery callback'и не вызываются и в логе trace ID генерируется как `sim-XXXXXX`.

#### `rover.dump_registry`
Выводит в лог текущее состояние registry (без криптоматериалов). Полезно для проверки pending queue и хешей.

Полей нет. Результат — одна或多行 DEBUG-записей с JSON-слепком:
```
REG DUMP meta={server_name:"Rover Hub",version:"0.3.0"} hash_m=ab12
REG DUMP users=[{hash:beef…,name:"Иван",role:owner}] hash_u=cd34
REG DUMP areas=3 hash_a=ef56
REG DUMP devices=12 hash_d=78ab
REG DUMP pending=[{hash:cafe…,name:"Маша"}] 1/10
```

### 078. Чек-лист диагностики по симптомам

| Симптом | Где смотреть | Что искать |
|---------|--------------|------------|
| App не получает PUSH | `hab` → `trn` | `THROTTLE FLUSH`? → `OUT [trace]`? → `DELIVERY`/`FAILED`? |
| App не видит новое устройство | `reg` → `trn` → `hnd` | `MUTATION add_device`? → `OUT [trace] tp=6` (PONG)? → `REQ`/`CONFIG`? |
| CMD не выполняется | `hnd` → `hab` | `CMD reject` (auth? unknown id?) → `SVC call`? → `SVC ERROR`? |
| Лишние/дублирующие PUSH | `hab` | `THROTTLE hit`? Если нет — проверять `trn` на bounce (loopback?). |
| Не приходит REGISTER | `trn` | `IN [trace] tp=9`? Если нет — `rns` (connectivity?) или `hnd` (mute?). |
| Identity потерялась | `trn` | `RNS init identity=…` — hash совпадает с предыдущим? |
| HACS не ставится | — | `manifest.json` version vs git tag; double-nesting в ZIP. |

## Часть 4: Открытые вопросы (для будущих решений)

### Закрытые вопросы

- **Q1.** Передавать ли роль `role` в секции `u` всем remote'ам? **Решено:** передаём всем. Household-friendly, не privacy-критично для v0.3.0.
- **Q5.** Сценарий миграции HA-сервера (как переносить identity на новое железо)? **Решено:** через Options Flow кнопка «Экспорт identity» — скачать файлы из `.reticulum/`. При reinstall интеграции, если файлы уже есть в `.reticulum/`, использовать их.
- **Q6.** Что делать если у пользователя 2 телефона — одна Identity на оба или две разные? **Решено:** две разные Identity. Каждый телефон — отдельный remote. Синхронизация state между телефонами — out of scope (Columba не синхронизирует). Если пользователь хочет один пульт на двух телефонах — экспорт/импорт identity через Columba.
- **Q7.** Кодировка строк в msgpack — всегда UTF-8? **Решено:** да, UTF-8. Emoji в именах поддерживаются.

### Оставшиеся открытые вопросы

- **Q2.** Как именно регистрировать blacklist отозванных identity (если регистрируем)?
- **Q3.** Когда добавлять Propagation Node поддержку — отдельный отказ от unicast PUSH?
- **Q4.** Поддерживать ли «гостевой» режим без регистрации (read-only state без CMD)?

Эти вопросы НЕ блокируют MVP. Возвращаемся к ним после первой работающей версии.