"""Tests for state_extractor.py."""
import pytest
from custom_components.rover.state_extractor import extract_state


def test_sw_on():
    assert extract_state("on", {}, "SW") == {"v": "on"}


def test_lt_brightness():
    st = extract_state("on", {"brightness": 255, "color_temp_kelvin": 2700}, "LT")
    assert st == {"v": "on", "b": 100, "ct": 2700}


def test_lt_rgb():
    st = extract_state("on", {"rgb_color": [255, 128, 0]}, "LT")
    assert st == {"v": "on", "rgb": [255, 128, 0]}


def test_cv():
    st = extract_state("open", {"current_position": 75, "current_tilt_position": 30}, "CV")
    assert st == {"v": "open", "p": 75, "ti": 30}


def test_cl():
    st = extract_state("heat", {
        "temperature": 22.5,
        "current_temperature": 20.0,
        "target_temp_high": 24.0,
        "target_temp_low": 18.0,
        "fan_mode": "auto",
        "preset_mode": "eco",
        "swing_mode": "on",
    }, "CL")
    assert st == {
        "v": "heat",
        "t": 22.5,
        "tc": 20.0,
        "th": 24.0,
        "tl": 18.0,
        "fan": "auto",
        "preset": "eco",
        "swing_h": "on",
    }


def test_lk():
    assert extract_state("locked", {}, "LK") == {"v": "locked"}


def test_ms():
    st = extract_state("playing", {
        "volume_level": 0.5,
        "media_title": "Song",
        "media_artist": "Artist",
        "media_album_name": "Album",
        "media_duration": 300,
        "media_position": 120,
        "is_volume_muted": False,
    }, "MS")
    assert st == {
        "v": "playing",
        "vol": 50,
        "title": "Song",
        "artist": "Artist",
        "album": "Album",
        "dur": 300,
        "pos": 120,
        "muted": False,
    }


def test_al():
    assert extract_state("triggered", {}, "AL") == {"v": "triggered"}


def test_se_unavailable():
    st = extract_state("unavailable", {"unit_of_measurement": "°C"}, "SE")
    assert st == {"v": "unavailable", "u": "°C"}


def test_se_number():
    st = extract_state("23.5", {"unit_of_measurement": "°C"}, "SE")
    assert st == {"v": "23.5", "u": "°C"}


def test_fn():
    st = extract_state("on", {"percentage": 33, "preset_mode": "auto", "oscillating": True, "direction": "forward"}, "FN")
    assert st == {"v": "on", "sp": 33, "preset": "auto", "osc": True, "dir": "forward"}


def test_bt_empty():
    assert extract_state("unknown", {}, "BT") == {}


def test_invalid_type():
    with pytest.raises(ValueError):
        extract_state("on", {}, "XX")
