# Rover — card

Карточка Lovelace для Home Assistant. Показывает статус Rover-сети, поток пакетов и предоставляет админ-функции.

## Что показывает

- **Шапка** — имя дома, количество подключённых фронтов, сколько из них онлайн.
- **Поток пакетов** — последние 200 входящих и исходящих пакетов с возможностью раскрыть подробности по клику.
- **Админ-вкладка** — QR для онбординга новых фронтов, список зарегистрированных фронтов. Доступ по паролю.

Управления отдельными устройствами в карточке нет — для этого есть нативные карточки HA.

## Установка

### Через HACS (рекомендуется)
1. HACS → Frontend → ⋮ → Custom repositories.
2. Добавить `https://github.com/BotoVed/Rover` как Lovelace.
3. Установить Rover Card.
4. Перезагрузить страницу Lovelace.

### Вручную
1. Скачать ZIP из последнего [card-релиза](https://github.com/BotoVed/Rover/releases?q=card).
2. Распаковать `rover-card.js` в `<HA_config>/www/community/rover-card/`.
3. Добавить в resources Lovelace:
   ```yaml
   resources:
     - url: /hacsfiles/rover-card/rover-card.js
       type: module
   ```
4. Перезагрузить страницу.

## Использование

На дашборде Lovelace: Add Card → Custom: Rover Card.

```yaml
type: custom:rover-card
```

Параметры конфигурации (опциональны):

```yaml
type: custom:rover-card
title: Rover Status
max_packets: 200
show_admin: true
```

## Документация

- [`../SPEC.md`](../SPEC.md) — спецификация протокола и системы, раздел §10 про карточку
- [`../DECISIONS.md`](../DECISIONS.md) — журнал архитектурных решений
- [`AGENT.md`](./AGENT.md) — инструкции для разработки

## Лицензия

[GPL v3](../LICENSE)
