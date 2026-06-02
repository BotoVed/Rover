from __future__ import annotations

import json
import logging
import os
from typing import Any

import voluptuous as vol

_LOGGER = logging.getLogger(__name__)
from homeassistant import config_entries
from homeassistant.config_entries import ConfigFlowResult
from homeassistant.helpers import selector
from homeassistant.helpers.selector import (
    SelectSelector,
    SelectSelectorConfig,
    TextSelector,
    TextSelectorConfig,
)

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

SUPPORTED_DOMAINS = list(HA_DOMAIN_TO_DEV_TYPE.keys())

_BASE_FIELDS = {
    vol.Required(CONF_HOME_NAME, default=""): str,
    vol.Required(CONF_CHANNEL, default="LongFast"): str,
    vol.Required(CONF_PSK, default="AQ=="): str,
    vol.Required(CONF_HOP_LIMIT, default=0):
        vol.All(vol.Coerce(int), vol.Range(min=0, max=7)),
    vol.Required(CONF_QUEUE_PERIOD, default=15):
        vol.All(vol.Coerce(int), vol.Range(min=5, max=60)),
    vol.Required(CONF_MAX_RETRIES, default=5):
        vol.All(vol.Coerce(int), vol.Range(min=1, max=20)),
    vol.Required(CONF_ACK_TIMEOUT, default=10):
        vol.All(vol.Coerce(int), vol.Range(min=5, max=30)),
    vol.Required(CONF_PUSH_ENABLED, default=True): bool,
}

async def _get_serial_ports(hass) -> list[str]:
    """Сканирует USB-порты, возвращает /dev/serial/by-id/* если доступно.

    Вся файловая работа — в executor, чтобы не блокировать event loop.
    """
    import os

    def _scan() -> list[str]:
        from serial.tools import list_ports
        ports: list[str] = []
        for p in list_ports.comports():
            device = p.device
            # Только ACM (USB-адаптеры) и USB (CH340/CP210x)
            if not (device.startswith("/dev/ttyACM") or device.startswith("/dev/ttyUSB")):
                continue
            real = os.path.realpath(device)
            by_id_dir = "/dev/serial/by-id/"
            if os.path.isdir(by_id_dir):
                # Ищем стабильный симплинк — он не меняется при перезагрузке
                for entry in sorted(os.listdir(by_id_dir)):
                    if os.path.realpath(os.path.join(by_id_dir, entry)) == real:
                        ports.append(os.path.join(by_id_dir, entry))
                        break
                else:
                    ports.append(device)
            else:
                ports.append(device)
        return ports if ports else ["/dev/ttyACM0"]
    try:
        return await hass.async_add_executor_job(_scan)
    except Exception:
        return ["/dev/ttyACM0"]


class RoverOptionsFlow(config_entries.OptionsFlow):
    def __init__(self, config_entry: config_entries.ConfigEntry) -> None:
        self._entry = config_entry
        self._last_action: str | None = None
        self._conn_type: str = "serial"

    async def async_step_init(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        try:
            return self.async_show_menu(
                step_id="init",
                menu_options=["general", "devices", "users_menu", "config_view", "test"],
                description_placeholders={
                    "last_action": self._last_action or "",
                },
            )
        except Exception:
            _LOGGER.exception("Rover options_flow async_step_init failed")
            raise

    # ---------- Общие ----------

    async def async_step_general(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        try:
            if user_input is not None:
                self._conn_type = user_input[CONF_CONN_TYPE]
                if self._conn_type == "serial":
                    return await self.async_step_general_serial()
                return await self.async_step_general_tcp()

            data = self._entry.data
            schema = vol.Schema({
                vol.Required(CONF_CONN_TYPE, default=data.get(CONF_CONN_TYPE, "serial")): SelectSelector(
                    SelectSelectorConfig(options=[
                        {"value": "serial", "label": "Serial (USB)"},
                        {"value": "tcp", "label": "TCP"},
                    ])
                ),
            })
            return self.async_show_form(step_id="general", data_schema=schema)
        except Exception:
            _LOGGER.exception("Rover options_flow async_step_general failed")
            raise

    async def async_step_general_serial(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        try:
            if user_input is not None:
                user_input[CONF_CONN_TYPE] = self._conn_type
                new_data = {**self._entry.data, **user_input}
                self.hass.config_entries.async_update_entry(self._entry, data=new_data)
                self._last_action = "Общие настройки обновлены"
                return await self.async_step_init()

            data = self._entry.data
            ports = await _get_serial_ports(self.hass)

            schema = vol.Schema({
                vol.Required(CONF_PORT, default=data.get(CONF_PORT, ports[0] if ports else "")): SelectSelector(
                    SelectSelectorConfig(options=[
                        {"value": p, "label": os.path.basename(p)} for p in ports
                    ])
                ),
                **{k: v for k, v in _BASE_FIELDS.items()},
            })
            return self.async_show_form(step_id="general_serial", data_schema=schema)
        except Exception:
            _LOGGER.exception("Rover options_flow async_step_general_serial failed")
            raise

    async def async_step_general_tcp(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        try:
            if user_input is not None:
                user_input[CONF_CONN_TYPE] = self._conn_type
                new_data = {**self._entry.data, **user_input}
                self.hass.config_entries.async_update_entry(self._entry, data=new_data)
                self._last_action = "Общие настройки обновлены"
                return await self.async_step_init()

            data = self._entry.data
            schema = vol.Schema({
                vol.Required(CONF_PORT, default=data.get(CONF_PORT, "")): TextSelector(TextSelectorConfig()),
                **{k: v for k, v in _BASE_FIELDS.items()},
            })
            return self.async_show_form(step_id="general_tcp", data_schema=schema)
        except Exception:
            _LOGGER.exception("Rover options_flow async_step_general_tcp failed")
            raise

    def _runtime(self):
        """Достаёт runtime_data из entry.

        getattr — защита от старых версий HA, где поля ConfigEntry ещё нет.
        """
        runtime = getattr(self._entry, 'runtime_data', None)
        if runtime is None:
            raise RuntimeError("Rover runtime data not available — entry not initialized")
        return runtime

    # ---------- Устройства ----------

    async def async_step_devices(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        try:
            runtime = self._runtime()
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
        except Exception:
            _LOGGER.exception("Rover options_flow async_step_devices failed")
            raise

    # ---------- Пользователи: меню ----------

    async def async_step_users_menu(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        try:
            runtime = self._runtime()
            registry = runtime.registry
            users_list = ", ".join(u.id for u in registry.all_users()) or "(пусто)"
            return self.async_show_menu(
                step_id="users_menu",
                menu_options=["user_add", "user_remove"],
                description_placeholders={"users": users_list},
            )
        except Exception:
            _LOGGER.exception("Rover options_flow async_step_users_menu failed")
            raise

    async def async_step_user_add(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        try:
            runtime = self._runtime()
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
        except Exception:
            _LOGGER.exception("Rover options_flow async_step_user_add failed")
            raise

    async def async_step_user_remove(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        try:
            runtime = self._runtime()
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
        except Exception:
            _LOGGER.exception("Rover options_flow async_step_user_remove failed")
            raise

    # ---------- Конфиг (read-only просмотр) ----------

    async def async_step_config_view(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        try:
            if user_input is not None:
                return await self.async_step_init()

            runtime = self._runtime()
            registry = runtime.registry

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
        except Exception:
            _LOGGER.exception("Rover options_flow async_step_config_view failed")
            raise

    # ---------- E2E тест ----------

    async def async_step_test(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        try:
            from .test_e2e import run_e2e_test

            runtime = self._runtime()
            await run_e2e_test(self.hass, runtime.transport, runtime.registry, runtime.dispatcher)
            self._last_action = "🧪 Тест выполнен — смотри логи"
            return await self.async_step_init()
        except Exception:
            _LOGGER.exception("Rover E2E test failed")
            self._last_action = "🧪 Тест упал — смотри логи"
            return await self.async_step_init()
