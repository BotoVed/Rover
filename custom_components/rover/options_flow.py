"""Options flow для Rover — мастер настроек после установки.

Главное меню (init):
- Общие — изменение базовых настроек подключения и параметров очереди.
- Устройства — multi-select из подходящих entity HA.
- Пользователи — добавление/удаление с хешированием пароля.
- Конфиг — read-only просмотр всех секций конфига в JSON для ручного переноса на фронт.

См. DECISIONS.md SB-041, SB-042, SB-043.
"""

from __future__ import annotations

import json
from typing import Any

import voluptuous as vol
from homeassistant import config_entries
from homeassistant.config_entries import ConfigFlowResult
from homeassistant.helpers import selector

from .const import (
    CONF_ACK_TIMEOUT,
    CONF_CHANNEL,
    CONF_CONN_TYPE,
    CONF_HOME_NAME,
    CONF_HOP_LIMIT,
    CONF_MAX_RETRIES,
    CONF_PASSWORD_SALT,
    CONF_PORT,
    CONF_PSK,
    CONF_PUSH_ENABLED,
    CONF_QUEUE_PERIOD,
    HA_DOMAIN_TO_DEV_TYPE,
    SEC_AREAS,
    SEC_DEVICES,
    SEC_META,
    SEC_USERS,
)

# Поддерживаемые домены для селектора устройств
SUPPORTED_DOMAINS = list(HA_DOMAIN_TO_DEV_TYPE.keys())

CONN_TYPES = ["serial", "tcp"]


class RoverOptionsFlow(config_entries.OptionsFlow):
    """OptionsFlow с меню разделов."""

    def __init__(self, config_entry: config_entries.ConfigEntry) -> None:
        self._entry = config_entry
        self._last_action: str | None = None

    async def async_step_init(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """Главное меню OptionsFlow."""
        return self.async_show_menu(
            step_id="init",
            menu_options=["general", "devices", "users_menu", "config_view"],
            description_placeholders={
                "last_action": self._last_action or "",
            },
        )

    # ---------- Общие ----------

    async def async_step_general(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """Редактирование общих настроек."""
        if user_input is not None:
            # Объединяем со старыми data (соль не трогаем)
            new_data = {**self._entry.data, **user_input}
            self.hass.config_entries.async_update_entry(self._entry, data=new_data)
            self._last_action = "Общие настройки обновлены"
            return await self.async_step_init()

        data = self._entry.data
        schema = vol.Schema({
            vol.Required(CONF_HOME_NAME, default=data.get(CONF_HOME_NAME, "")): str,
            vol.Required(CONF_CONN_TYPE, default=data.get(CONF_CONN_TYPE, "serial")):
                vol.In(CONN_TYPES),
            vol.Required(CONF_PORT, default=data.get(CONF_PORT, "")): str,
            vol.Required(CONF_CHANNEL, default=data.get(CONF_CHANNEL, "LongFast")): str,
            vol.Required(CONF_PSK, default=data.get(CONF_PSK, "AQ==")): str,
            vol.Required(CONF_HOP_LIMIT, default=data.get(CONF_HOP_LIMIT, 0)):
                vol.All(vol.Coerce(int), vol.Range(min=0, max=7)),
            vol.Required(CONF_QUEUE_PERIOD, default=data.get(CONF_QUEUE_PERIOD, 15)):
                vol.All(vol.Coerce(int), vol.Range(min=5, max=60)),
            vol.Required(CONF_MAX_RETRIES, default=data.get(CONF_MAX_RETRIES, 5)):
                vol.All(vol.Coerce(int), vol.Range(min=1, max=20)),
            vol.Required(CONF_ACK_TIMEOUT, default=data.get(CONF_ACK_TIMEOUT, 10)):
                vol.All(vol.Coerce(int), vol.Range(min=5, max=30)),
            vol.Required(CONF_PUSH_ENABLED, default=data.get(CONF_PUSH_ENABLED, True)): bool,
        })
        return self.async_show_form(step_id="general", data_schema=schema)

    # ---------- Устройства ----------

    async def async_step_devices(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """Multi-select устройств. Уже зарегистрированные — отмечены."""
        runtime = self._entry.runtime_data
        registry = runtime.registry

        if user_input is not None:
            selected = set(user_input.get("entities", []))
            current = {d.entity_id for d in registry.all_devices()}

            to_add = selected - current
            to_remove = current - selected

            for entity_id in to_add:
                state = self.hass.states.get(entity_id)
                if state is None:
                    continue
                domain = entity_id.split(".", 1)[0]
                name = state.attributes.get("friendly_name", entity_id)
                area = state.attributes.get("area_id")
                unit = state.attributes.get("unit_of_measurement")
                registry.register(entity_id, domain, name, area=area, unit=unit)

            for entity_id in to_remove:
                registry.remove_device_by_entity_id(entity_id)

            added = len(to_add)
            removed = len(to_remove)
            parts = []
            if added:
                parts.append(f"добавлено {added}")
            if removed:
                parts.append(f"удалено {removed}")
            self._last_action = (
                "Устройства: " + ", ".join(parts) if parts else "Устройства без изменений"
            )

            return await self.async_step_init()

        current_entity_ids = [d.entity_id for d in registry.all_devices()]
        schema = vol.Schema({
            vol.Required("entities", default=current_entity_ids):
                selector.EntitySelector(
                    selector.EntitySelectorConfig(
                        domain=SUPPORTED_DOMAINS,
                        multiple=True,
                    )
                ),
        })
        return self.async_show_form(step_id="devices", data_schema=schema)

    # ---------- Пользователи: меню ----------

    async def async_step_users_menu(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """Меню действий с пользователями."""
        runtime = self._entry.runtime_data
        registry = runtime.registry
        users_list = ", ".join(u.id for u in registry.all_users()) or "(пусто)"
        return self.async_show_menu(
            step_id="users_menu",
            menu_options=["user_add", "user_remove"],
            description_placeholders={"users": users_list},
        )

    async def async_step_user_add(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """Добавление пользователя: имя + пароль."""
        runtime = self._entry.runtime_data
        registry = runtime.registry

        if user_input is not None:
            salt = self._entry.data.get(CONF_PASSWORD_SALT, "")
            registry.add_user_with_password(
                user_id=user_input["name"],
                password=user_input["password"],
                salt=salt,
            )
            self._last_action = f"Пользователь {user_input['name']} добавлен"
            return await self.async_step_init()

        schema = vol.Schema({
            vol.Required("name"): str,
            vol.Required("password"): str,
        })
        return self.async_show_form(step_id="user_add", data_schema=schema)

    async def async_step_user_remove(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """Удаление пользователя: выбор из существующих."""
        runtime = self._entry.runtime_data
        registry = runtime.registry

        if user_input is not None:
            removed = registry.remove_user(user_input["name"])
            self._last_action = (
                f"Пользователь {user_input['name']} удалён"
                if removed else
                f"Пользователь {user_input['name']} не найден"
            )
            return await self.async_step_init()

        user_ids = [u.id for u in registry.all_users()]
        if not user_ids:
            self._last_action = "Нет пользователей для удаления"
            return await self.async_step_init()

        schema = vol.Schema({
            vol.Required("name"): vol.In(user_ids),
        })
        return self.async_show_form(step_id="user_remove", data_schema=schema)

    # ---------- Конфиг (read-only просмотр) ----------

    async def async_step_config_view(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """Просмотр текущих секций конфига в JSON для копирования."""
        if user_input is not None:
            return await self.async_step_init()

        runtime = self._entry.runtime_data
        registry = runtime.registry

        # Собираем meta-секцию из config_entry
        data = self._entry.data
        meta_dict = {
            "n": data.get(CONF_HOME_NAME, ""),
            "ch": data.get(CONF_CHANNEL, ""),
            "key": data.get(CONF_PSK, ""),
            "upd": data.get(CONF_QUEUE_PERIOD, 15),
            "rty": data.get(CONF_MAX_RETRIES, 5),
            "ack": data.get(CONF_ACK_TIMEOUT, 10),
            "psh": 1 if data.get(CONF_PUSH_ENABLED, True) else 0,
            "hop": data.get(CONF_HOP_LIMIT, 0),
            "salt": data.get(CONF_PASSWORD_SALT, ""),
        }

        meta_hash = registry.hash_meta(meta_dict)
        section_hashes = registry.compute_section_hashes()

        meta_json = json.dumps(meta_dict, ensure_ascii=False, indent=2)
        users_json = json.dumps(registry.export_users(), ensure_ascii=False, indent=2)
        areas_json = json.dumps(registry.export_areas(), ensure_ascii=False, indent=2)
        devices_json = json.dumps(registry.export_devices(), ensure_ascii=False, indent=2)

        schema = vol.Schema({
            vol.Optional(f"meta ({meta_hash})", default=meta_json): str,
            vol.Optional(f"users ({section_hashes[SEC_USERS]})", default=users_json): str,
            vol.Optional(f"areas ({section_hashes[SEC_AREAS]})", default=areas_json): str,
            vol.Optional(f"devices ({section_hashes[SEC_DEVICES]})", default=devices_json): str,
        })
        return self.async_show_form(step_id="config_view", data_schema=schema)
