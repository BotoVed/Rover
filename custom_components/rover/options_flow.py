"""Options flow for Rover integration.

Menu structure:
  init / general / devices / device_remove / device_test / users / pending / config
"""
from __future__ import annotations

import base64
import io
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
    MAX_PENDING_REMOTES,
    QR_FORMAT_VERSION,
    TYPE_DEFS,
)

_LOGGER = logging.getLogger(LOGGER_ROOT)

SUPPORTED_DOMAINS = sorted(
    {v["domain"] for v in TYPE_DEFS.values()} | {"binary_sensor"}
)

_DEVICE_ACTIONS = {
    "turn_on": "Turn on",
    "turn_off": "Turn off",
    "press": "Press (button)",
    "toggle": "Toggle",
}

_QR_IMAGE_CACHE: dict[str, str] = {}


def _qr_data_uri(data: str) -> str:
    """Generate QR code as base64 PNG data URI. Cached by input."""
    cached = _QR_IMAGE_CACHE.get(data)
    if cached:
        return cached
    try:
        import qrcode
        qr = qrcode.QRCode(box_size=5, border=2)
        qr.add_data(data)
        img = qr.make_image()
        buf = io.BytesIO()
        img.save(buf, format="PNG")
        b64 = base64.b64encode(buf.getvalue()).decode()
        uri = f"data:image/png;base64,{b64}"
        _QR_IMAGE_CACHE[data] = uri
        return uri
    except ImportError:
        return ""


def _format_device_list(devices: list[dict]) -> str:
    if not devices:
        return "(none)"
    lines = []
    for d in devices:
        area = d.get("area_id")
        area_str = f" [area:{area}]" if area else ""
        lines.append(f"  #{d['short_id']} {d['name']} ({d['type']}){area_str}")
    return "\n".join(lines)


class RoverOptionsFlow(config_entries.OptionsFlow):
    """Multi-step options flow for Rover."""

    def __init__(self, config_entry: config_entries.ConfigEntry) -> None:
        self._config_entry = config_entry

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
                "general", "devices", "device_remove", "device_test",
                "users", "pending", "config",
            ],
        )

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

        existing = registry.all_devices()
        existing_text = _format_device_list(existing)

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
                "count": str(len(existing)),
                "device_list": existing_text,
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
                description_placeholders={"count": "0"},
            )

        options = [
            {"value": str(d["short_id"]), "label": f"{d['short_id']}: {d['name']} ({d['type']})"}
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
            description_placeholders={"count": str(len(devices))},
        )

    # ---------- device_test ----------
    async def async_step_device_test(self, user_input: dict | None = None) -> FlowResult:
        registry = self._registry
        devices = registry.all_devices()

        if user_input is not None:
            sid = int(user_input["device_id"])
            action = user_input["action"]
            device = registry.get_device(sid)
            if device is not None:
                entity_id = device["entity_id"]
                try:
                    if action == "turn_on":
                        await self.hass.services.async_call(
                            "homeassistant", "turn_on", {"entity_id": entity_id}, blocking=True
                        )
                    elif action == "turn_off":
                        await self.hass.services.async_call(
                            "homeassistant", "turn_off", {"entity_id": entity_id}, blocking=True
                        )
                    elif action == "toggle":
                        await self.hass.services.async_call(
                            "homeassistant", "toggle", {"entity_id": entity_id}, blocking=True
                        )
                    elif action == "press":
                        domain = entity_id.split(".", 1)[0]
                        await self.hass.services.async_call(
                            domain, "press", {"entity_id": entity_id}, blocking=True
                        )
                    _LOGGER.info("Test %s %s → OK", entity_id, action)
                except Exception as e:
                    _LOGGER.error("Test %s %s → FAILED: %s", entity_id, action, e)
            return self._back_to_menu()

        if not devices:
            return self.async_show_form(
                step_id="device_test",
                data_schema=vol.Schema({}),
                description_placeholders={"count": "0"},
            )

        device_options = [
            {"value": str(d["short_id"]), "label": f"#{d['short_id']} {d['name']} ({d['type']})"}
            for d in devices
        ]
        return self.async_show_form(
            step_id="device_test",
            data_schema=vol.Schema(
                {
                    vol.Required("device_id"): SelectSelector(
                        SelectSelectorConfig(
                            options=device_options,
                            multiple=False,
                            mode=SelectSelectorMode.LIST,
                        )
                    ),
                    vol.Required("action", default="toggle"): SelectSelector(
                        SelectSelectorConfig(
                            options=[
                                {"value": k, "label": v}
                                for k, v in _DEVICE_ACTIONS.items()
                            ],
                            multiple=False,
                            mode=SelectSelectorMode.LIST,
                        )
                    ),
                }
            ),
            description_placeholders={"count": str(len(devices))},
        )

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
                    "active": "0", "max": str(MAX_ACTIVE_REMOTES)},
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
                _LOGGER.info("Options: reject for %s... (no-op)", chosen[:8])
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
                            options=options, multiple=False, mode=SelectSelectorMode.LIST,
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
        qr_text = json.dumps(qr_payload, ensure_ascii=False)

        qr_image = _qr_data_uri(qr_text)
        devices = registry.all_devices()
        users = registry.all_users()

        if user_input is not None:
            return self._back_to_menu()

        return self.async_show_form(
            step_id="config",
            data_schema=vol.Schema({}),
            description_placeholders={
                "identity": ihash,
                "server_name": meta.get("server_name", "Rover Hub"),
                "version": meta.get("version", "—"),
                "qr_payload": qr_text,
                "qr_image": qr_image or "",
                "device_count": str(len(devices)),
                "user_count": str(len(users)),
            },
        )
