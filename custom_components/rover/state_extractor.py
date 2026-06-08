"""Extract Rover protocol state from HA state string and attributes."""
from __future__ import annotations


def extract_state(state: str, attributes: dict | None, device_type: str) -> dict:
    attributes = attributes or {}

    # SW
    if device_type == "SW":
        return {"v": state}

    # LT
    if device_type == "LT":
        result = {"v": state}
        b = attributes.get("brightness")
        if b is not None:
            result["b"] = round(b * 100 / 255)
        ct = attributes.get("color_temp_kelvin")
        if ct is not None:
            result["ct"] = ct
        rgb = attributes.get("rgb_color")
        if rgb is not None:
            result["rgb"] = rgb
        ef = attributes.get("effect")
        if ef is not None:
            result["ef"] = ef
        return result

    # CV
    if device_type == "CV":
        result = {"v": state}
        p = attributes.get("current_position")
        if p is not None:
            result["p"] = p
        t = attributes.get("current_tilt_position")
        if t is not None:
            result["ti"] = t
        return result

    # CL
    if device_type == "CL":
        result = {"v": state}
        t = attributes.get("temperature")
        if t is not None:
            result["t"] = t
        tc = attributes.get("current_temperature")
        if tc is not None:
            result["tc"] = tc
        th = attributes.get("target_temp_high")
        if th is not None:
            result["th"] = th
        tl = attributes.get("target_temp_low")
        if tl is not None:
            result["tl"] = tl
        fan = attributes.get("fan_mode")
        if fan is not None:
            result["fan"] = fan
        preset = attributes.get("preset_mode")
        if preset is not None:
            result["preset"] = preset
        swing_h = attributes.get("swing_mode")
        if swing_h is not None:
            result["swing_h"] = swing_h
        return result

    # LK
    if device_type == "LK":
        return {"v": state}

    # MS
    if device_type == "MS":
        result = {"v": state}
        vol = attributes.get("volume_level")
        if vol is not None:
            result["vol"] = round(vol * 100)
        title = attributes.get("media_title")
        if title is not None:
            result["title"] = title
        artist = attributes.get("media_artist")
        if artist is not None:
            result["artist"] = artist
        album = attributes.get("media_album_name")
        if album is not None:
            result["album"] = album
        dur = attributes.get("media_duration")
        if dur is not None:
            result["dur"] = dur
        pos = attributes.get("media_position")
        if pos is not None:
            result["pos"] = pos
        muted = attributes.get("is_volume_muted")
        if muted is not None:
            result["muted"] = muted
        return result

    # SC
    if device_type == "SC":
        return {}

    # AL
    if device_type == "AL":
        return {"v": state}

    # SE
    if device_type == "SE":
        result = {"v": str(state)}
        u = attributes.get("unit_of_measurement")
        if u is not None:
            result["u"] = u
        return result

    # FN
    if device_type == "FN":
        result = {"v": state}
        sp = attributes.get("percentage")
        if sp is not None:
            result["sp"] = sp
        preset = attributes.get("preset_mode")
        if preset is not None:
            result["preset"] = preset
        osc = attributes.get("oscillating")
        if osc is not None:
            result["osc"] = osc
        direc = attributes.get("direction")
        if direc is not None:
            result["dir"] = direc
        return result

    # BT
    if device_type == "BT":
        return {}

    raise ValueError(f"Unknown device type: {device_type}")
