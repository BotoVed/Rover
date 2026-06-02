"""E2E test for Rover integration. Remove before release."""
from __future__ import annotations

import logging
import random
import time

import msgpack

_LOGGER = logging.getLogger(__name__)

PRIVATE_APP_PORT = 256


async def run_e2e_test(hass, transport, registry):
    """Run E2E test: send PING, then CMD to first switch."""
    _LOGGER.info("=== Rover E2E Test START ===")

    ts = int(time.time())
    ping = msgpack.packb({"tp": 6, "ts": ts, "h": {}}, use_bin_type=True)
    _LOGGER.info("[TEST] Sending PING ts=%d", ts)
    await hass.async_add_executor_job(transport.send_raw, ping)

    await hass.async_add_executor_job(_send_switch_cmd, transport, registry)

    _LOGGER.info("=== Rover E2E Test DONE (watch logs for PONG/PUSH) ===")


def _send_switch_cmd(transport, registry):
    """Find first SW device and send CMD turn_on."""
    devices = registry.all_devices()
    switch = None
    for dev in devices:
        if dev.t == "SW":
            switch = dev
            break

    if switch is None:
        _LOGGER.info(
            "[TEST] No switch found in registry. Devices: %s",
            {d.short_id: d.t for d in devices},
        )
        return

    cmid = random.randint(0, 65535)
    cmd = msgpack.packb(
        {"tp": 5, "id": switch.short_id, "s": True, "cmid": cmid}, use_bin_type=True
    )
    _LOGGER.info(
        "[TEST] Sending CMD turn_on to SW id=0x%04x name=%s cmid=%d",
        switch.short_id,
        switch.n or "?",
        cmid,
    )
    transport.send_raw(cmd)
