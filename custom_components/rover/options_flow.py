"""Options flow for Rover integration."""
from __future__ import annotations

import json
import logging
from typing import Any

import voluptuous as vol

from homeassistant import config_entries
from homeassistant.core import callback
from homeassistant.data_entry_flow import FlowResult
from homeassistant.helpers.selector import (
    EntitySelector,
    EntitySelectorConfig,
    SelectSelector,
    SelectSelectorConfig,
    SelectSelectorMode,
)

from .const import (
    DOMAIN,
    DOMAIN_TO_TYPE,
    LOGGER_ROOT,
    MAX_ACTIVE_REMOTES,
    QR_FORMAT_VERSION,
    TYPE_DEFS,
)

_LOGGER = logging.getLogger(LOGGER_ROOT)

SUPPORTED_DOMAINS = sorted(
    {v["domain"] for v in TYPE_DEFS.values()} | {"binary_sensor"}
)

TESTABLE_BOOL_TYPES = {"SW", "LT", "LK", "FN"}
TESTABLE_ACTIVATION_TYPES = {"SC", "BT"}


def _render_qr_unicode(payload: str) -> str:
    """Render text payload as a QR code using Unicode half-blocks."""
    try:
        import qrcode
    except ImportError:
        return "[qrcode lib not available]"

    qr = qrcode.QRCode(
        version=None,
        error_correction=qrcode.constants.ERROR_CORRECT_L,
        box_size=1,
        border=2,
    )
    qr.add_data(payload)
    qr.make(fit=True)
    matrix = qr.get_matrix()

    lines = []
    for y in range(0, len(matrix), 2):
        row = []
        for x in range(len(matrix[y])):
            upper = matrix[y][x]
            lower = matrix[y + 1][x] if y + 1 < len(matrix) else False
            if upper and lower:
                row.append("█")
            elif upper:
                row.append("▀")
            elif lower:
                row.append("▄")
            else:
                row.append(" ")
        lines.append("".join(row))
    return "\n".join(lines)


def _format_device_list(devices: list[dict], max_items: int = 30) -> str:
    """Format list of devices for description display."""
    if not devices:
        return "—"
    lines = []
    for d in devices[:max_items]:
        sid = d["short_id"]
        name = d["name"]
        type_code = d["type"]
        entity = d["entity_id"]
        enabled = "✓" if d.get("enabled", True) else "✗"
        lines.append(f"  {enabled} #{sid} {name} [{type_code}] {entity}")
    if len(devices) > max_items:
        lines.append(f"  …и ещё {len(devices) - max_items}")
    return "\n".join(lines)


class RoverOptionsFlow(config_entries.OptionsFlow):
    """Multi-step options flow for Rover."""

    def __init__(self, config_entry: config_entries.ConfigEntry) -> None:
        self._config_entry = config_entry
        self._test_short_id: int | None = None

    @property
    def _runtime(self):
        return self._config_entry.runtime_data

    @property
    def _registry(self):
        rt = self._runtime
        return rt.registry if rt else None

    @property
    def _identity_hash(self) -> str | None:
        rt = self._runtime
        return rt.identity_hash if rt else None

    def _back_to_menu(self) -> FlowResult:
        return self.async_show_menu(
            step_id="init",
            menu_options=[
                "general",
                "devices",
                "device_remove",
                "test_device",
                "users",
                "pending",
                "config",
            ],
        )

    # ---------- init ----------
    async def async_step_init(self, user_input: dict | None = None) -> FlowResult:
        if self._registry is None:
            return self.async_abort(reason="not_loaded")
        return self._back_to_menu()

    # ---------- general ----------
    async def async_step_general(self, user_input: dict | None = None) -> FlowResult:
        registry = self._registry
        if user_input is not None:
            new_name = str(user_input["server_name"]).strip()
            if new_name:
                await registry.set_server_name(new_name)
            return self._back_to_menu()

        meta = registry.get_meta()
        return self.async_show_form(
            step_id="general",
            data_schema=vol.Schema(
                {
                    vol.Required(
                        "server_name", default=meta.get("server_name", "Rover Hub")
                    ): str,
                }
            ),
        )

    # ---------- devices (add) ----------
    async def async_step_devices(self, user_input: dict | None = None) -> FlowResult:
        registry = self._registry

        if user_input is not None:
            selected = user_input.get("entities", []) or []
            added = 0
            for entity_id in selected:
                if registry.get_device_by_entity_id(entity_id):
                    continue
                domain = entity_id.split(".", 1)[0] if "." in entity_id else ""
                type_code = DOMAIN_TO_TYPE.get(domain)
                if type_code is None:
                    continue
                ha_state = self.hass.states.get(entity_id)
                display = (
                    ha_state.attributes.get("friendly_name") if ha_state else None
                ) or entity_id
                try:
                    await registry.add_device(entity_id, display, type_code)
                    added += 1
                except ValueError as e:
                    _LOGGER.warning("add_device failed for %s: %s", entity_id, e)
            _LOGGER.info("Options: added %d device(s)", added)
            return self._back_to_menu()

        devices = registry.all_devices()
        return self.async_show_form(
            step_id="devices",
            data_schema=vol.Schema(
                {
                    vol.Optional("entities", default=[]): EntitySelector(
                        EntitySelectorConfig(
                            domain=SUPPORTED_DOMAINS, multiple=True
                        )
                    ),
                }
            ),
            description_placeholders={
                "count": str(len(devices)),
                "device_list": _format_device_list(devices),
            },
        )

    # ---------- device_remove ----------
    async def async_step_device_remove(self, user_input: dict | None = None) -> FlowResult:
        registry = self._registry
        devices = registry.all_devices()

        if user_input is not None:
            ids = user_input.get("device_ids", []) or []
            removed = 0
            for sid_str in ids:
                try:
                    sid = int(sid_str)
                except (TypeError, ValueError):
                    continue
                if await registry.remove_device(sid):
                    removed += 1
            _LOGGER.info("Options: removed %d device(s)", removed)
            return self._back_to_menu()

        if not devices:
            return self.async_show_form(
                step_id="device_remove",
                data_schema=vol.Schema({}),
                description_placeholders={
                    "count": "0",
                    "device_list": "—",
                },
            )

        options = [
            {
                "value": str(d["short_id"]),
                "label": f"#{d['short_id']} {d['name']} ({d['type']}) — {d['entity_id']}",
            }
            for d in devices
        ]
        return self.async_show_form(
            step_id="device_remove",
            data_schema=vol.Schema(
                {
                    vol.Optional("device_ids", default=[]): SelectSelector(
                        SelectSelectorConfig(
                            options=options,
                            multiple=True,
                            mode=SelectSelectorMode.LIST,
                        )
                    ),
                }
            ),
            description_placeholders={
                "count": str(len(devices)),
                "device_list": _format_device_list(devices),
            },
        )

    # ---------- test_device ----------
    async def async_step_test_device(self, user_input: dict | None = None) -> FlowResult:
        """Step 1: pick device. Step 2 (async_step_test_action): pick action."""
        registry = self._registry
        devices = [
            d for d in registry.all_devices()
            if d.get("enabled", True)
            and d["type"] in (TESTABLE_BOOL_TYPES | TESTABLE_ACTIVATION_TYPES)
        ]

        if user_input is not None:
            try:
                self._test_short_id = int(user_input["device_id"])
            except (TypeError, ValueError, KeyError):
                self._test_short_id = None
                return self._back_to_menu()
            return await self.async_step_test_action()

        if not devices:
            return self.async_show_form(
                step_id="test_device",
                data_schema=vol.Schema({}),
                description_placeholders={
                    "device_list": "— no testable devices —"
                },
            )

        options = [
            {
                "value": str(d["short_id"]),
                "label": f"#{d['short_id']} {d['name']} [{d['type']}] — {d['entity_id']}",
            }
            for d in devices
        ]
        return self.async_show_form(
            step_id="test_device",
            data_schema=vol.Schema(
                {
                    vol.Required("device_id"): SelectSelector(
                        SelectSelectorConfig(
                            options=options,
                            multiple=False,
                            mode=SelectSelectorMode.LIST,
                        )
                    ),
                }
            ),
            description_placeholders={
                "device_list": _format_device_list(devices),
            },
        )

    async def async_step_test_action(self, user_input: dict | None = None) -> FlowResult:
        """Pick action and execute via handlers.handle_cmd."""
        registry = self._registry
        runtime = self._runtime

        if self._test_short_id is None:
            return self._back_to_menu()

        device = registry.get_device(self._test_short_id)
        if device is None:
            self._test_short_id = None
            return self._back_to_menu()

        device_type = device["type"]

        if user_input is not None:
            action = user_input.get("action")
            cmd_fields = self._build_cmd_for_action(device_type, action)
            if cmd_fields is None:
                self._test_short_id = None
                return self._back_to_menu()

            cmd_payload = {"tp": 5, "id": self._test_short_id, **cmd_fields}
            _LOGGER.info(
                "TEST UI exec id=%d type=%s action=%s fields=%s",
                self._test_short_id, device_type, action, cmd_fields,
            )

            if runtime is not None and runtime.handlers is not None:
                fake_src_hex = "ff" * 16
                fake_src_bytes = bytes.fromhex(fake_src_hex)
                added = False
                if not registry.is_approved(fake_src_hex):
                    added = await registry.add_pending(fake_src_hex, "_test_ui")
                    if added:
                        await registry.approve_pending(fake_src_hex)
                try:
                    await runtime.handlers.handle_cmd(fake_src_bytes, cmd_payload)
                finally:
                    if added:
                        await registry.revoke_user(fake_src_hex)

            self._test_short_id = None
            return self._back_to_menu()

        action_options = self._action_options_for_type(device_type)
        if not action_options:
            self._test_short_id = None
            return self._back_to_menu()

        return self.async_show_form(
            step_id="test_action",
            data_schema=vol.Schema(
                {
                    vol.Required("action"): SelectSelector(
                        SelectSelectorConfig(
                            options=action_options,
                            multiple=False,
                            mode=SelectSelectorMode.LIST,
                        )
                    ),
                }
            ),
            description_placeholders={
                "device": f"#{device['short_id']} {device['name']} [{device_type}] — {device['entity_id']}",
            },
        )

    @staticmethod
    def _action_options_for_type(device_type: str) -> list[dict]:
        if device_type in TESTABLE_BOOL_TYPES:
            return [
                {"value": "on", "label": "On"},
                {"value": "off", "label": "Off"},
            ]
        if device_type in TESTABLE_ACTIVATION_TYPES:
            return [{"value": "activate", "label": "Activate"}]
        return []

    @staticmethod
    def _build_cmd_for_action(device_type: str, action: str) -> dict | None:
        if device_type in TESTABLE_BOOL_TYPES:
            if action == "on":
                return {"s": True}
            if action == "off":
                return {"s": False}
        if device_type in TESTABLE_ACTIVATION_TYPES:
            if action == "activate":
                return {}
        return None

    # ---------- users ----------
    async def async_step_users(self, user_input: dict | None = None) -> FlowResult:
        registry = self._registry
        users = registry.all_users()

        if user_input is not None:
            hashes = user_input.get("user_hashes", []) or []
            revoked = 0
            for h in hashes:
                if await registry.revoke_user(h):
                    revoked += 1
            _LOGGER.info("Options: revoked %d user(s)", revoked)
            return self._back_to_menu()

        if not users:
            return self.async_show_form(
                step_id="users",
                data_schema=vol.Schema({}),
                description_placeholders={
                    "active": "0",
                    "max": str(MAX_ACTIVE_REMOTES),
                },
            )

        options = [
            {
                "value": u["hash"],
                "label": f"{u['name']} ({u['role']}) — {u['hash'][:8]}…",
            }
            for u in users
        ]
        return self.async_show_form(
            step_id="users",
            data_schema=vol.Schema(
                {
                    vol.Optional("user_hashes", default=[]): SelectSelector(
                        SelectSelectorConfig(
                            options=options,
                            multiple=True,
                            mode=SelectSelectorMode.LIST,
                        )
                    ),
                }
            ),
            description_placeholders={
                "active": str(len(users)),
                "max": str(MAX_ACTIVE_REMOTES),
            },
        )

    # ---------- pending ----------
    async def async_step_pending(self, user_input: dict | None = None) -> FlowResult:
        registry = self._registry
        pending = registry.all_pending()

        if user_input is not None:
            action = user_input.get("action")
            chosen = user_input.get("pending_hash")
            if action == "approve" and chosen:
                if await registry.approve_pending(chosen):
                    _LOGGER.info("Options: approved %s...", chosen[:8])
            elif action == "reject" and chosen:
                _LOGGER.info(
                    "Options: reject for %s... (remove_pending not implemented)", chosen[:8]
                )
            return self._back_to_menu()

        if not pending:
            return self.async_show_form(
                step_id="pending",
                data_schema=vol.Schema({}),
                description_placeholders={"count": "0"},
            )

        options = [
            {"value": p["hash"], "label": f"{p['name']} — {p['hash'][:8]}…"}
            for p in pending
        ]
        return self.async_show_form(
            step_id="pending",
            data_schema=vol.Schema(
                {
                    vol.Required("pending_hash"): SelectSelector(
                        SelectSelectorConfig(
                            options=options, multiple=False,
                            mode=SelectSelectorMode.LIST,
                        )
                    ),
                    vol.Required("action", default="approve"): SelectSelector(
                        SelectSelectorConfig(
                            options=[
                                {"value": "approve", "label": "Approve"},
                                {"value": "reject", "label": "Reject"},
                            ],
                            multiple=False,
                            mode=SelectSelectorMode.LIST,
                        )
                    ),
                }
            ),
            description_placeholders={"count": str(len(pending))},
        )

    # ---------- config ----------
    async def async_step_config(self, user_input: dict | None = None) -> FlowResult:
        registry = self._registry
        meta = registry.get_meta()
        ihash = self._identity_hash or "(not initialized)"

        qr_payload = {
            "rvr": {
                "fmt": QR_FORMAT_VERSION,
                "dst": ihash,
                "nm": meta.get("server_name", "Rover Hub"),
            }
        }
        qr_json = json.dumps(qr_payload, ensure_ascii=False)
        qr_image = _render_qr_unicode(qr_json)

        if user_input is not None:
            return self._back_to_menu()

        return self.async_show_form(
            step_id="config",
            data_schema=vol.Schema({}),
            description_placeholders={
                "identity": ihash,
                "server_name": meta.get("server_name", "Rover Hub"),
                "version": meta.get("version", "—"),
                "qr_payload": qr_json,
                "qr_image": qr_image,
            },
        )
