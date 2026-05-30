# Rover — back

Плагин Home Assistant (custom integration). Мост между HA и Meshtastic-шлюзом.

## Что делает

- Подключается к локальной Meshtastic-ноде через USB или TCP.
- Регистрирует выбранные устройства HA, выдаёт им компактные 2-байтовые ID.
- Принимает команды от Rover-приложений по LoRa, исполняет в HA.
- Отслеживает изменения состояний устройств и алертов, рассылает их в эфир.

## Установка

### Через HACS (рекомендуется)
1. HACS → Integrations → ⋮ → Custom repositories.
2. Добавить `https://github.com/BotoVed/Rover` как Integration.
3. Установить Rover.
4. Перезапустить Home Assistant.
5. Settings → Integrations → Add → Rover.

### Вручную
1. Скачать ZIP из последнего [back-релиза](https://github.com/BotoVed/Rover/releases?q=back).
2. Распаковать `rover/` в `<HA_config>/custom_components/`.
3. Перезапустить HA.

## Конфигурация

Минимальный пример `configuration.yaml`:

```yaml
rover:
  meshtastic:
    port: /dev/serial/by-id/usb-1a86_USB_Serial-if00-port0
    channel: LongFast
    psk: AQ==
    hop_limit: 0
  queue:
    period: 15
    max_retries: 5
  alerts:
    period: 15
    device_classes: [door, motion, smoke, gas]
  devices:
    include:
      - light.salon_main
      - switch.kitchen_outlet
      - climate.living_room
```

## Документация

- [`../SPEC.md`](../SPEC.md) — спецификация протокола и системы
- [`../DECISIONS.md`](../DECISIONS.md) — журнал архитектурных решений
- [`AGENT.md`](./AGENT.md) — инструкции для разработки

## Лицензия

[GPL v3](../LICENSE)
