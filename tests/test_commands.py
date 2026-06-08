"""Tests for commands.py."""
import pytest
from custom_components.rover.commands import build_service_call


def test_sw_on():
    assert build_service_call("SW", {"s": True}) == [("switch", "turn_on", {})]


def test_sw_off():
    assert build_service_call("SW", {"s": False}) == [("switch", "turn_off", {})]


def test_lt_on_brightness():
    calls = build_service_call("LT", {"s": True, "b": 75})
    assert calls == [("light", "turn_on", {"brightness": 191})]


def test_lt_off():
    assert build_service_call("LT", {"s": False}) == [("light", "turn_off", {})]


def test_lt_rgb_ct_ef():
    calls = build_service_call("LT", {"s": True, "rgb": [255, 128, 0], "ct": 2700, "ef": "colorloop"})
    assert calls == [("light", "turn_on", {"rgb_color": [255, 128, 0], "color_temp_kelvin": 2700, "effect": "colorloop"})]


def test_cv_open():
    assert build_service_call("CV", {"cv": "open"}) == [("cover", "open_cover", {})]


def test_cv_set_tilt():
    calls = build_service_call("CV", {"cv": "set", "p": 50, "ti": 25})
    assert ("cover", "set_cover_position", {"position": 50}) in calls
    assert ("cover", "set_cover_tilt_position", {"tilt_position": 25}) in calls


def test_cl_hvac_temp():
    calls = build_service_call("CL", {"hvac": "heat", "t": 22.5})
    assert ("climate", "set_hvac_mode", {"hvac_mode": "heat"}) in calls
    assert ("climate", "set_temperature", {"temperature": 22.5}) in calls


def test_cl_swing_preset():
    calls = build_service_call("CL", {"swing_h": "on", "preset": "eco"})
    assert ("climate", "set_swing_mode", {"swing_mode": "on"}) in calls
    assert ("climate", "set_preset_mode", {"preset_mode": "eco"}) in calls


def test_lk_lock():
    assert build_service_call("LK", {"s": True}) == [("lock", "lock", {})]


def test_lk_unlock():
    assert build_service_call("LK", {"s": False}) == [("lock", "unlock", {})]


def test_ms_play():
    assert build_service_call("MS", {"ms": "play"}) == [("media_player", "media_play", {})]


def test_ms_vol():
    assert build_service_call("MS", {"ms": "vol", "vol": 30}) == [("media_player", "volume_set", {"volume_level": 0.3})]


def test_ms_mute():
    assert build_service_call("MS", {"ms": "mute"}) == [("media_player", "volume_mute", {"is_volume_muted": True})]


def test_ms_seek():
    assert build_service_call("MS", {"seek": 120}) == [("media_player", "media_seek", {"seek_position": 120})]


def test_sc():
    assert build_service_call("SC", {}) == [("scene", "turn_on", {})]


def test_al_arm_home():
    assert build_service_call("AL", {"al": "arm_home"}) == [("alarm_control_panel", "alarm_arm_home", {})]


def test_al_disarm():
    assert build_service_call("AL", {"al": "disarm"}) == [("alarm_control_panel", "alarm_disarm", {})]


def test_al_invalid():
    with pytest.raises(ValueError):
        build_service_call("AL", {"al": "invalid"})


def test_se_empty():
    assert build_service_call("SE", {}) == []


def test_fn_on_speed():
    calls = build_service_call("FN", {"s": True, "sp": 50})
    assert ("fan", "turn_on", {}) in calls
    assert ("fan", "set_percentage", {"percentage": 50}) in calls


def test_fn_osc():
    assert build_service_call("FN", {"osc": True}) == [("fan", "oscillate", {"oscillating": True})]


def test_bt():
    assert build_service_call("BT", {}) == [("button", "press", {})]


def test_invalid_type():
    with pytest.raises(ValueError):
        build_service_call("XX", {})
