"""Rover — Home Assistant integration.

Точка входа интеграции. Использует современные паттерны HA:
- async_setup_entry для каждого config entry
- entry.runtime_data для хранения состояния
- async_add_executor_job для блокирующих вызовов meshtastic-библиотеки

См. DECISIONS.md SB-034.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from typing import TYPE_CHECKING

from .const import DOMAIN
from .registry import Registry

if TYPE_CHECKING:
    from homeassistant.config_entries import ConfigEntry
    from homeassistant.core import HomeAssistant

__version__ = "0.2.3"

_LOGGER = logging.getLogger(__name__)


@dataclass
class RoverRuntimeData:
    """Контейнер для долгоживущих ресурсов интеграции.

    Хранится в entry.runtime_data, доступен из всех частей интеграции.
    """
    registry: Registry
    # Транспорт, очередь, диспетчер, обработчики — будут добавлены на следующих
    # этапах разработки.


type RoverConfigEntry = ConfigEntry[RoverRuntimeData]


async def async_setup_entry(
    hass: HomeAssistant,  # type: ignore[name-defined]  # noqa: F821
    entry: RoverConfigEntry,
) -> bool:
    """Точка входа интеграции для config entry.

    Вызывается HA при загрузке. Возвращает True при успехе.
    """
    _LOGGER.info("Rover: setting up entry %s (title=%s)", entry.entry_id, entry.title)

    # Создаём Registry — пока без устройств, они будут регистрироваться отдельно
    registry = Registry()

    # Сохраняем долгоживущие ресурсы в entry.runtime_data
    entry.runtime_data = RoverRuntimeData(registry=registry)

    # TODO (back-0.1.8+): инициализация transport, queue, dispatcher, handlers.
    # Все блокирующие вызовы Meshtastic-библиотеки оборачивать в:
    #     await hass.async_add_executor_job(blocking_call, ...)

    _LOGGER.info("Rover: entry %s ready", entry.entry_id)
    return True


async def async_unload_entry(
    hass: HomeAssistant,  # type: ignore[name-defined]  # noqa: F821
    entry: RoverConfigEntry,
) -> bool:
    """Выгрузка интеграции.

    Закрывает соединения, отписывается от событий HA.
    """
    _LOGGER.info("Rover: unloading entry %s", entry.entry_id)

    # TODO (back-0.1.8+): закрытие transport, отмена подписок.

    return True
