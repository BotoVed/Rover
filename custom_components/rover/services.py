"""Rover debug/test services: set_loglevel, send_test_message, simulate_inbound, dump_registry."""
from __future__ import annotations

import asyncio
import json
import logging
from typing import TYPE_CHECKING, Any

import voluptuous as vol

from homeassistant.core import HomeAssistant, ServiceCall
from homeassistant.helpers import config_validation as cv

from .const import (
    DOMAIN,
    LOGGER_HAB,
    LOGGER_HND,
    LOGGER_REG,
    LOGGER_RNS,
    LOGGER_ROOT,
    LOGGER_TRN,
)

if TYPE_CHECKING:
    from . import RoverRuntimeData

_LOGGER = logging.getLogger(LOGGER_ROOT)

DEFAULT_LEVELS: dict[str, int] = {
    LOGGER_ROOT: logging.INFO,
    LOGGER_REG: logging.INFO,
    LOGGER_HND: logging.INFO,
    LOGGER_TRN: logging.DEBUG,
    LOGGER_HAB: logging.DEBUG,
    LOGGER_RNS: logging.WARNING,
}

LEVEL_MAP: dict[str, int] = {
    "debug": logging.DEBUG,
    "info": logging.INFO,
    "warning": logging.WARNING,
    "error": logging.ERROR,
}

SERVICE_SET_LOGLEVEL = "set_loglevel"
SERVICE_SEND_TEST_MESSAGE = "send_test_message"
SERVICE_SIMULATE_INBOUND = "simulate_inbound"
SERVICE_DUMP_REGISTRY = "dump_registry"

SCHEMA_SET_LOGLEVEL = vol.Schema(
    {
        vol.Required("level"): vol.In(list(LEVEL_MAP.keys())),
        vol.Optional("duration_minutes", default=30): cv.positive_int,
    }
)

SCHEMA_SEND_TEST_MESSAGE = vol.Schema(
    {
        vol.Required("destination_hash"): str,
        vol.Required("tp"): vol.All(int, vol.Range(min=2, max=9)),
        vol.Optional("payload", default={}): vol.Any(dict, str),
    }
)

SCHEMA_SIMULATE_INBOUND = vol.Schema(
    {
        vol.Required("source_hash"): str,
        vol.Required("tp"): vol.All(int, vol.Range(min=2, max=9)),
        vol.Optional("payload", default={}): vol.Any(dict, str),
        vol.Optional("authorized", default=False): bool,
    }
)


def _restore_default_levels() -> None:
    for name, lvl in DEFAULT_LEVELS.items():
        logging.getLogger(name).setLevel(lvl)


def _coerce_payload(payload: Any) -> dict | None:
    if isinstance(payload, dict):
        return payload
    if isinstance(payload, str):
        if not payload.strip():
            return {}
        try:
            parsed = json.loads(payload)
        except json.JSONDecodeError:
            return None
        return parsed if isinstance(parsed, dict) else None
    return None


async def async_register_services(
    hass: HomeAssistant, runtime: "RoverRuntimeData"
) -> None:
    """Register Rover debug services."""
    state: dict[str, Any] = {"loglevel_restore_handle": None}

    async def handle_set_loglevel(call: ServiceCall) -> None:
        level_name = str(call.data.get("level", "info")).lower()
        duration = int(call.data.get("duration_minutes", 30))
        level = LEVEL_MAP.get(level_name)
        if level is None:
            _LOGGER.warning("set_loglevel: invalid level=%r", level_name)
            return

        for name in DEFAULT_LEVELS:
            logging.getLogger(name).setLevel(level)
        _LOGGER.info(
            "Log level set to %s across all Rover loggers for %d min",
            level_name.upper(),
            duration,
        )

        prev_handle = state.get("loglevel_restore_handle")
        if prev_handle is not None:
            prev_handle.cancel()

        def _restore() -> None:
            _restore_default_levels()
            _LOGGER.info("Log levels restored to production defaults")

        state["loglevel_restore_handle"] = hass.loop.call_later(
            duration * 60, _restore
        )

    async def handle_send_test_message(call: ServiceCall) -> None:
        if runtime.transport is None:
            _LOGGER.warning("send_test_message: transport not initialized")
            return

        dst_raw = str(call.data.get("destination_hash", ""))
        if dst_raw == "self":
            if runtime.identity_hash is None:
                _LOGGER.warning("send_test_message: own identity_hash not set yet")
                return
            dst_hex = runtime.identity_hash
        else:
            dst_hex = dst_raw.strip().lower()
            if len(dst_hex) != 32 or not all(c in "0123456789abcdef" for c in dst_hex):
                _LOGGER.warning(
                    "send_test_message: invalid destination_hash=%r (expected 32-hex or 'self')",
                    dst_raw,
                )
                return

        tp = int(call.data["tp"])
        payload = _coerce_payload(call.data.get("payload", {}))
        if payload is None:
            _LOGGER.warning("send_test_message: payload not a valid dict/JSON")
            return

        fields = {"tp": tp, **payload}
        _LOGGER.info(
            "TEST send dst=%s... tp=%d fields_keys=%s",
            dst_hex[:8],
            tp,
            list(fields.keys()),
        )
        try:
            await runtime.transport.send(dst_hex, fields)
        except Exception:
            _LOGGER.exception("TEST send failed")

    async def handle_simulate_inbound(call: ServiceCall) -> None:
        if runtime.dispatcher is None:
            _LOGGER.warning(
                "simulate_inbound: dispatcher not wired yet (waiting on Phase 2.5)"
            )
            return

        src_hex = str(call.data.get("source_hash", "")).strip().lower()
        if len(src_hex) != 32 or not all(c in "0123456789abcdef" for c in src_hex):
            _LOGGER.warning("simulate_inbound: invalid source_hash=%r", src_hex)
            return

        tp = int(call.data["tp"])
        payload = _coerce_payload(call.data.get("payload", {}))
        if payload is None:
            _LOGGER.warning("simulate_inbound: payload not a valid dict/JSON")
            return

        authorized = bool(call.data.get("authorized", False))
        fields = {"tp": tp, **payload}
        src_bytes = bytes.fromhex(src_hex)

        _LOGGER.info(
            "SIM inbound src=%s... tp=%d authorized=%s fields_keys=%s",
            src_hex[:8], tp, authorized, list(fields.keys()),
        )

        needs_cleanup = False
        if authorized and not runtime.registry.is_approved(src_hex):
            added = await runtime.registry.add_pending(src_hex, "_test_sim")
            if added:
                await runtime.registry.approve_pending(src_hex)
                needs_cleanup = True

        try:
            await runtime.dispatcher.dispatch(src_bytes, fields)
        finally:
            if needs_cleanup:
                await runtime.registry.revoke_user(src_hex)

    async def handle_dump_registry(call: ServiceCall) -> None:
        reg = runtime.registry
        if reg is None:
            _LOGGER.warning("dump_registry: registry not initialized")
            return

        hashes = reg.get_hashes()
        _LOGGER.info("REG DUMP meta=%s hash_m=%s", reg.get_meta(), hashes["m"])

        users = reg.all_users()
        _LOGGER.info("REG DUMP users=%d hash_u=%s", len(users), hashes["u"])
        for u in users:
            _LOGGER.info(
                "  user: hash=%s... name=%r role=%s",
                u["hash"][:8], u["name"], u["role"],
            )

        areas = reg.all_areas()
        _LOGGER.info("REG DUMP areas=%d hash_a=%s", len(areas), hashes["a"])
        for a in areas:
            _LOGGER.info("  area: id=%d name=%r", a["id"], a["name"])

        devices = reg.all_devices()
        _LOGGER.info("REG DUMP devices=%d hash_d=%s", len(devices), hashes["d"])
        for d in devices:
            _LOGGER.info(
                "  device: id=%d name=%r type=%s entity=%s area=%s enabled=%s",
                d["short_id"], d["name"], d["type"], d["entity_id"],
                d.get("area_id"), d.get("enabled", True),
            )

        pending = reg.all_pending()
        _LOGGER.info("REG DUMP pending=%d", len(pending))
        for p in pending:
            _LOGGER.info("  pending: hash=%s... name=%r", p["hash"][:8], p["name"])

    if not hass.services.has_service(DOMAIN, SERVICE_SET_LOGLEVEL):
        hass.services.async_register(
            DOMAIN, SERVICE_SET_LOGLEVEL,
            handle_set_loglevel, schema=SCHEMA_SET_LOGLEVEL,
        )
    if not hass.services.has_service(DOMAIN, SERVICE_SEND_TEST_MESSAGE):
        hass.services.async_register(
            DOMAIN, SERVICE_SEND_TEST_MESSAGE,
            handle_send_test_message, schema=SCHEMA_SEND_TEST_MESSAGE,
        )
    if not hass.services.has_service(DOMAIN, SERVICE_SIMULATE_INBOUND):
        hass.services.async_register(
            DOMAIN, SERVICE_SIMULATE_INBOUND,
            handle_simulate_inbound, schema=SCHEMA_SIMULATE_INBOUND,
        )
    if not hass.services.has_service(DOMAIN, SERVICE_DUMP_REGISTRY):
        hass.services.async_register(
            DOMAIN, SERVICE_DUMP_REGISTRY, handle_dump_registry
        )

    _LOGGER.info("Rover debug services registered")


def async_unregister_services(hass: HomeAssistant) -> None:
    for name in (
        SERVICE_SET_LOGLEVEL,
        SERVICE_SEND_TEST_MESSAGE,
        SERVICE_SIMULATE_INBOUND,
        SERVICE_DUMP_REGISTRY,
    ):
        if hass.services.has_service(DOMAIN, name):
            hass.services.async_remove(DOMAIN, name)
