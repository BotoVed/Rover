"""E2E test for Rover integration. Remove before release."""
from __future__ import annotations

import logging
import random
import time

import msgpack

_LOGGER = logging.getLogger(__name__)

PRIVATE_APP_PORT = 256


async def run_e2e_test(hass, transport, registry, dispatcher):
    """Run E2E test: send PING, then simulate incoming CMD via dispatcher."""
    _LOGGER.info("=== Rover E2E Test START ===")

    ts = int(time.time())
    ping = msgpack.packb({"tp": 6, "ts": ts, "h": {}}, use_bin_type=True)
    _LOGGER.info("[TEST] Sending PING ts=%d", ts)
    await hass.async_add_executor_job(transport.send_raw, ping)

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
    else:
        cmid = random.randint(0, 65535)
        cmd_dict = {"tp": 5, "id": switch.short_id, "s": True, "cmid": cmid}
        _LOGGER.info(
            "[TEST] Simulating incoming CMD turn_on to SW id=0x%04x name=%s cmid=%d",
            switch.short_id,
            switch.n or "?",
            cmid,
        )
        await dispatcher.dispatch(cmd_dict, from_node=0x99999999)

    _LOGGER.info("=== Rover E2E Test DONE — switch should toggle now ===")
