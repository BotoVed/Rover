"""Build HA service calls from Rover CMD messages."""
from __future__ import annotations

from .const import TYPE_TO_DOMAIN


def build_service_call(device_type: str, cmd_fields: dict) -> list[tuple[str, str, dict]]:
    if device_type not in TYPE_TO_DOMAIN:
        raise ValueError(f"Unknown device type: {device_type}")

    # SW
    if device_type == "SW":
        s = cmd_fields.get("s")
        if s is True:
            return [("switch", "turn_on", {})]
        return [("switch", "turn_off", {})]

    # LT
    if device_type == "LT":
        if cmd_fields.get("s") is False:
            return [("light", "turn_off", {})]
        service_data = {}
        if "b" in cmd_fields:
            service_data["brightness"] = round(cmd_fields["b"] * 2.55)
        if "ct" in cmd_fields:
            service_data["color_temp_kelvin"] = cmd_fields["ct"]
        if "rgb" in cmd_fields:
            service_data["rgb_color"] = cmd_fields["rgb"]
        if "ef" in cmd_fields:
            service_data["effect"] = cmd_fields["ef"]
        return [("light", "turn_on", service_data)]

    # CV
    if device_type == "CV":
        calls: list[tuple[str, str, dict]] = []
        cv = cmd_fields.get("cv")
        if cv == "open":
            calls.append(("cover", "open_cover", {}))
        elif cv == "close":
            calls.append(("cover", "close_cover", {}))
        elif cv == "stop":
            calls.append(("cover", "stop_cover", {}))
        elif cv == "set":
            calls.append(("cover", "set_cover_position", {"position": cmd_fields["position"]}))
        if "t" in cmd_fields:
            calls.append(("cover", "set_cover_tilt_position", {"tilt_position": cmd_fields["t"]}))
        return calls

    # CL
    if device_type == "CL":
        calls = []
        if "hvac" in cmd_fields:
            calls.append(("climate", "set_hvac_mode", {"hvac_mode": cmd_fields["hvac"]}))
        if "t" in cmd_fields:
            calls.append(("climate", "set_temperature", {"temperature": cmd_fields["t"]}))
        if "th" in cmd_fields or "tl" in cmd_fields:
            sd = {}
            if "th" in cmd_fields:
                sd["target_temp_high"] = cmd_fields["th"]
            if "tl" in cmd_fields:
                sd["target_temp_low"] = cmd_fields["tl"]
            calls.append(("climate", "set_temperature", sd))
        if "fan" in cmd_fields:
            calls.append(("climate", "set_fan_mode", {"fan_mode": cmd_fields["fan"]}))
        if "preset" in cmd_fields:
            calls.append(("climate", "set_preset_mode", {"preset_mode": cmd_fields["preset"]}))
        if "swing_h" in cmd_fields:
            calls.append(("climate", "set_swing_mode", {"swing_mode": cmd_fields["swing_h"]}))
        elif "swing_v" in cmd_fields:
            calls.append(("climate", "set_swing_mode", {"swing_mode": cmd_fields["swing_v"]}))
        return calls

    # LK
    if device_type == "LK":
        if cmd_fields.get("s") is True:
            return [("lock", "lock", {})]
        return [("lock", "unlock", {})]

    # MS
    if device_type == "MS":
        calls = []
        ms = cmd_fields.get("ms")
        if ms == "play":
            calls.append(("media_player", "media_play", {}))
        elif ms == "pause":
            calls.append(("media_player", "media_pause", {}))
        elif ms == "stop":
            calls.append(("media_player", "media_stop", {}))
        elif ms == "next":
            calls.append(("media_player", "media_next_track", {}))
        elif ms == "prev":
            calls.append(("media_player", "media_previous_track", {}))
        elif ms == "vol" and "vol" in cmd_fields:
            calls.append(("media_player", "volume_set", {"volume_level": cmd_fields["vol"] / 100}))
        elif ms == "mute":
            calls.append(("media_player", "volume_mute", {"is_volume_muted": True}))
        elif ms == "unmute":
            calls.append(("media_player", "volume_mute", {"is_volume_muted": False}))
        if "seek" in cmd_fields:
            calls.append(("media_player", "media_seek", {"seek_position": cmd_fields["seek"]}))
        return calls

    # SC
    if device_type == "SC":
        return [("scene", "turn_on", {})]

    # AL
    if device_type == "AL":
        al = cmd_fields.get("al")
        valid_modes = ["arm_home", "arm_away", "arm_night", "disarm"]
        if al not in valid_modes:
            raise ValueError(f"Invalid alarm mode: {al}")
        service = al
        return [("alarm_control_panel", f"alarm_{service}", {})]

    # SE — read-only
    if device_type == "SE":
        return []

    # FN
    if device_type == "FN":
        calls = []
        s = cmd_fields.get("s")
        if s is True:
            calls.append(("fan", "turn_on", {}))
        elif s is False:
            calls.append(("fan", "turn_off", {}))
        if "sp" in cmd_fields:
            calls.append(("fan", "set_percentage", {"percentage": cmd_fields["sp"]}))
        if "preset" in cmd_fields:
            calls.append(("fan", "set_preset_mode", {"preset_mode": cmd_fields["preset"]}))
        osc = cmd_fields.get("osc")
        if osc is True:
            calls.append(("fan", "oscillate", {"oscillating": True}))
        elif osc is False:
            calls.append(("fan", "oscillate", {"oscillating": False}))
        if "dir" in cmd_fields:
            calls.append(("fan", "set_direction", {"direction": cmd_fields["dir"]}))
        return calls

    # BT
    if device_type == "BT":
        return [("button", "press", {})]

    return []
