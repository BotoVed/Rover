# Rover / card — Agent Instructions

Карточка Lovelace для дашборда Home Assistant. Отображает статус Rover-сети, поток пакетов и предоставляет админ-функции (QR онбординга).

## Repository
https://github.com/BotoVed/Rover (монорепо)
Эта папка: `card/`
Локальный путь: `tmp/rover/card/`

## Обязательное чтение перед работой
1. [`../SPEC.md`](../SPEC.md) — спецификация продукта, раздел §10 про карточку.
2. [`../DECISIONS.md`](../DECISIONS.md) — журнал архитектурных решений.
3. Этот файл — операционные инструкции.

При расхождении приоритет: SPEC → DECISIONS → AGENT.

## Environment
| | |
|---|---|
| OS | Ubuntu 24 |
| Node.js | 20.x LTS |
| Package manager | npm |
| Bundler | Rollup |
| Project | `tmp/rover/card/` |
| Package | `rover-card` |

## Workflow
```
read AGENT.md + ../SPEC.md + ../DECISIONS.md
→ write/change code
→ install: npm install
→ build:   npm run build              → выход: dist/rover-card.js
→ dev:     npm run watch              → автосборка при изменениях
→ test:    npm test                   → юнит-тесты (vitest)
→ deploy:  cp dist/rover-card.js <HA_config>/www/community/rover-card/
→ HA:      убедиться, что карточка добавлена в resources Lovelace
→ logs:    в браузере DevTools → Console (фильтр "rover-card")
→ commit + push (patch x.y.1)
→ test → fix → patch x.y.2, x.y.3 …
→ итоговый тест → commit + push (minor x.(y+1).0)
→ git tag card-x.(y+1).0 + GitHub Release с ZIP (для HACS)
→ обновить AGENT.md (после минора) и DECISIONS.md (если меняли логику)
```

```bash
# commit template
git add -A && git commit -m "card vX.Y.Z — description" && git push origin main

# tag + release
git tag card-X.Y.Z && git push origin card-X.Y.Z
# затем GitHub Release с ZIP содержимого dist/ (для HACS frontend)
```

## Project Structure
```
card/
├── README.md
├── AGENT.md                          — этот файл
├── package.json
├── tsconfig.json
├── rollup.config.js
├── hacs.json                         — манифест для HACS frontend
└── src/
    ├── rover-card.ts                 — точка входа, регистрация custom element
    ├── editor.ts                     — визуальный редактор карточки в Lovelace
    │
    ├── components/
    │   ├── header.ts                 — шапка: имя дома, фронты онлайн/всего
    │   ├── packet-list.ts            — скроллируемый список пакетов
    │   ├── packet-row.ts             — строка пакета (свёрнутая)
    │   ├── packet-details.ts         — раскрытые детали пакета
    │   └── admin-panel.ts            — админ-вкладка с QR
    │
    ├── state/
    │   ├── store.ts                  — состояние карточки (пакеты, фронты, имя дома)
    │   └── ha-bridge.ts              — подписка на entity / events Rover
    │
    ├── types/
    │   └── packet.ts                 — типы пакетов (CMD, PUSH, STATUS, ...)
    │
    └── util/
        ├── decode.ts                 — декодирование данных пакета для отображения
        └── time.ts                   — форматирование времени HH:MM:SS
```

## Application Protocol (Rover поверх Meshtastic)

Карточка не общается с Meshtastic напрямую. Источник данных — Home Assistant: бэк публикует события и entity, карточка их слушает.

Полная спецификация — в `../SPEC.md`. Сводка типов пакетов, которые карточка отображает:

| tp | Направление | Назначение |
|----|-------------|------------|
| 2 STATUS | HA → app | Состояние устройства в ответ на запрос |
| 3 PUSH | HA → app | Изменение состояния |
| 4 CONFIG | HA → app | Конфиг (META или секции) |
| 5 CMD | app → HA | Команда или запрос |
| 6 PING / PONG | app ↔ HA | Keepalive |
| 7 FRAGMENT | любое | Фрагмент крупного сообщения |

### Источник данных
Бэк (`back/`) публикует:
- **Entity `sensor.rover_status`** — атрибуты: `home_name`, `fronts_total`, `fronts_online`.
- **HA event `rover_packet`** — каждый входящий/исходящий пакет: `{direction, ts, from_node, tp, data}`.

Карточка слушает event и накапливает в локальном буфере (последние 200 пакетов).

## Содержание карточки

### Шапка
- Имя дома (`home_name` из META).
- Фронты: `online / total` (например, `2 / 3 online`).

### Поток пакетов
Скроллируемый список последних 200 пакетов. Строка содержит:
- Направление: ↓ (входящий) / ↑ (исходящий).
- Время (HH:MM:SS).
- Имя ноды (`from_node`).
- Тип пакета (CMD / PUSH / PING / STATUS / CONFIG / FRAGMENT).
- Вторая строка — минимальные данные: `short_id` устройства, ключевые поля.

При клике на строку — раскрытие в полные данные пакета (key: value по всем полям).

### Админ-раздел
Кнопка «Админ» открывает отдельную вкладку. Перед открытием — ввод пароля пользователя. Механизм валидации пароля — через HA service `rover.verify_password` (детали в SPEC).

В админ-вкладке:
- QR-код для онбординга нового фронта (имя канала Meshtastic + PSK + node ID шлюза).
- Список зарегистрированных фронтов с возможностью отзыва.

## Dependencies
```json
{
  "dependencies": {
    "lit": "^3.1.0",
    "custom-card-helpers": "^1.9.0",
    "qrcode": "^1.5.3"
  },
  "devDependencies": {
    "typescript": "^5.3.0",
    "rollup": "^4.9.0",
    "@rollup/plugin-node-resolve": "^15.2.0",
    "@rollup/plugin-typescript": "^11.1.0",
    "@rollup/plugin-terser": "^0.4.0",
    "vitest": "^1.0.0"
  }
}
```

## Critical Patterns
- LitElement-компоненты — не использовать React-паттерны (нет JSX, есть html-tagged-template-literals).
- `setConfig` — обязательный метод карточки, валидирует параметры Lovelace.
- `getCardSize` — возвращает примерный размер в строках для авто-раскладки HA.
- Все подписки на HA events отписываются в `disconnectedCallback`.
- Буфер пакетов — 200 элементов, FIFO. При переполнении старые удаляются.
- Типизация HA объекта — через `HomeAssistant` из `custom-card-helpers`.
- TypeScript strict mode — обязательно. Не использовать `any` без `// @ts-ignore` с комментарием почему.

## Соглашения по коду
- Компоненты в `components/` — без состояния, чистые рендеры от props.
- Состояние — только в `state/store.ts`, доступ через события или Lit context.
- Сетевые операции (подписка на HA, вызовы services) — только в `state/ha-bridge.ts`.
- Один компонент = один файл.
- Имена custom elements — kebab-case с префиксом `rover-` (`rover-packet-list`, `rover-admin-panel`).

## Релизы
При каждом минорном повышении версии:
1. `npm run build` — собирает `dist/rover-card.js`.
2. `git tag card-X.Y.0`.
3. `git push origin card-X.Y.0`.
4. GitHub Release с ZIP-архивом содержимого `dist/` (для HACS frontend).
5. Обновить версию в `package.json` и `hacs.json`.

## Что обновлять после изменений
- Изменили поведение карточки, протокол с бэком, формат events → **../SPEC.md** + **../DECISIONS.md** (синхронно).
- Изменили команды билда, структуру проекта, добавили зависимость, минорное повышение версии → **AGENT.md**.
