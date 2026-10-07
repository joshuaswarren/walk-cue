from datetime import datetime
from zoneinfo import ZoneInfo

import pytest

from walkcue.cue import prompt_for
from walkcue.models import Place, Scene, Spot, Weather
from walkcue.phrasing import (
    InvalidArea,
    chat_completions_url,
    format_distance,
    format_temp,
    normalize_area,
    offline_cue,
    parse_model_cue,
)
from walkcue.service import placeholder_scene


def _weather(**overrides) -> Weather:
    base = dict(
        available=True,
        temp_c=16.0,
        weather_code=0,
        wind_kmh=10.0,
        precip_mm=0.0,
        is_day=True,
        local_time="10:00",
        hour=10,
        minute=0,
    )
    base.update(overrides)
    return Weather(**base)


def _scene(weather: Weather, spots: tuple[Spot, ...] = ()) -> Scene:
    return Scene(
        place=Place("Lisbon", "Lisbon, Portugal", 38.7, -9.1, "PT", False),
        weather=weather,
        spots=spots,
        spots_note=None,
    )


def test_area_rejects_blank_and_symbols():
    assert normalize_area("  Lisbon  ") == "Lisbon"
    with pytest.raises(InvalidArea):
        normalize_area("   ")
    with pytest.raises(InvalidArea):
        normalize_area("@@@")


def test_offline_cue_is_deterministic_and_rain_is_short():
    scene = _scene(_weather(weather_code=63, precip_mm=1.4, temp_c=11, hour=15, local_time="15:00"))
    first = offline_cue(scene)
    second = offline_cue(scene)
    assert first == second
    assert first.duration_minutes == 12
    assert first.source == "mock"
    assert first.why_now


def test_cold_night_stays_short_and_lit():
    cue = offline_cue(
        _scene(_weather(temp_c=3, weather_code=3, hour=22, is_day=False, local_time="22:15"))
    )
    assert cue.duration_minutes == 15
    assert "lit" in cue.why_now
    assert "37°F" in cue.why_now
    assert "°C" not in cue.why_now


def test_hot_clear_afternoon_stays_short():
    cue = offline_cue(_scene(_weather(temp_c=32, weather_code=0, hour=15)))
    assert cue.duration_minutes == 15
    assert "shade" in cue.vibe or "shade" in cue.why_now


def test_parser_accepts_fenced_json_and_rejects_prose():
    text = """```json
{"duration_minutes": 44, "vibe": "Quiet River Loop.", "why_now": "The air is mild enough to leave now"}
```"""
    cue = parse_model_cue(text, "gemma3")
    assert cue is not None
    assert cue.duration_minutes == 40
    assert cue.vibe == "quiet river loop"
    assert cue.why_now.endswith(".")
    assert cue.source == "model"
    assert cue.model == "gemma3"
    assert parse_model_cue("take a walk", "gemma3") is None


def test_units_and_distance():
    assert format_temp(20) == "68°F"
    assert format_temp(17.5) == "64°F"
    assert format_temp(3) == "37°F"
    assert format_distance(800) == "0.5 mi"
    assert format_distance(420) == "0.3 mi"
    assert format_distance(1500) == "0.9 mi"
    assert format_distance(100) == "330 ft"
    assert format_distance(40) == "nearby"
    assert "°C" not in (format_temp(17.5) or "")
    assert "km" not in format_distance(1500)
    assert not format_distance(420).endswith(" m")


def test_chat_url_accepts_root_or_v1():
    assert chat_completions_url("http://127.0.0.1:11434/v1") == (
        "http://127.0.0.1:11434/v1/chat/completions"
    )
    assert chat_completions_url("http://127.0.0.1:11434") == (
        "http://127.0.0.1:11434/v1/chat/completions"
    )
    assert chat_completions_url("http://127.0.0.1:1234/v1/chat/completions") == (
        "http://127.0.0.1:1234/v1/chat/completions"
    )


def test_placeholder_prompt_has_no_coordinates():
    moment = datetime(2026, 10, 5, 9, 30, tzinfo=ZoneInfo("UTC"))
    scene = placeholder_scene("Anytown", now=moment)
    prompt = prompt_for(scene)
    assert "Anytown" in prompt
    assert "latitude" not in prompt
    assert "0.0" not in prompt
    assert "64°F" in prompt
    assert "°C" not in prompt
    assert scene.place.demo is True
    assert [spot.name for spot in scene.spots] == ["North Meadow", "Canal Path", "Little Hill"]
