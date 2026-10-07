"""Turn conditions into a short, repeatable walk. No randomness."""

from __future__ import annotations

import math
import re
from datetime import datetime

from walkcue.models import Cue, Scene, Spot, Weather

# Exact strings reserved so the placeholder never hits a map service.
PLACEHOLDERS = {"anytown", "anytown, usa"}

DURATIONS = {
    "storm": 8,
    "rain": 12,
    "snow": 20,
    "hot": 15,
    "cold": 18,
    "wind": 18,
    "night": 15,
    "golden": 30,
    "gray": 22,
    "fair": 25,
    "unknown": 20,
}

VIBES: dict[str, tuple[str, ...]] = {
    "storm": ("short sheltered loop", "covered block and back"),
    "rain": ("brief tree-lined loop", "quick neighborhood circuit"),
    "snow": ("quiet snow walk", "slow bright loop"),
    "hot": ("shaded short loop", "easy shade walk"),
    "cold": ("brisk out-and-back", "fast warming loop"),
    "wind": ("sheltered side streets", "low and out of the wind"),
    "night": ("short lit loop", "easy lamp-lit circuit"),
    "golden": ("unhurried golden loop", "long easy wander"),
    "gray": ("steady gray-day loop", "calm neighborhood walk"),
    "fair": ("easy open loop", "relaxed neighborhood walk", "steady out-and-back"),
    "unknown": ("easy out-and-back", "short neighborhood loop"),
}


class InvalidArea(ValueError):
    pass


class AreaNotFound(LookupError):
    pass


class UpstreamError(RuntimeError):
    pass


def normalize_area(value: str) -> str:
    cleaned = " ".join(value.strip().split())
    if not cleaned:
        raise InvalidArea("Type a city or a ZIP code.")
    if len(cleaned) > 80:
        raise InvalidArea("That place name is too long.")
    if not re.fullmatch(r"[\w .,'’-]{1,80}", cleaned, flags=re.UNICODE):
        raise InvalidArea("Use a city name or a postal code.")
    if not re.search(r"[\w]", cleaned, flags=re.UNICODE):
        raise InvalidArea("Use a city name or a postal code.")
    return cleaned


def is_placeholder(area: str) -> bool:
    return area.casefold() in PLACEHOLDERS


def local_clock(now: datetime | None = None) -> tuple[int, int, str]:
    moment = now or datetime.now().astimezone()
    return moment.hour, moment.minute, moment.strftime("%H:%M")


def client_now(value: str | None) -> datetime | None:
    """Accept HH:MM from the browser. Anything else is ignored."""
    if not value:
        return None
    match = re.fullmatch(r"([01]\d|2[0-3]):([0-5]\d)", value.strip())
    if not match:
        return None
    hour, minute = int(match.group(1)), int(match.group(2))
    return datetime.now().astimezone().replace(
        hour=hour, minute=minute, second=0, microsecond=0
    )


def _rounded(value: float) -> int:
    if value >= 0:
        return int(math.floor(value + 0.5))
    return int(math.ceil(value - 0.5))


def format_temp(temp_c: float | None) -> str | None:
    """Display temperature in Fahrenheit. Upstream values stay Celsius."""
    if temp_c is None or not math.isfinite(temp_c):
        return None
    return f"{_rounded(temp_c * 9 / 5 + 32)}°F"


def format_distance(meters: int) -> str:
    """Display distance in miles, or feet under a tenth of a mile."""
    if meters < 80:
        return "nearby"
    miles = meters / 1609.344
    if miles < 0.1:
        feet = int(round(meters * 3.280839895 / 10.0) * 10)
        return f"{feet} ft"
    return f"{miles:.1f} mi"


def condition_label(code: int | None) -> str:
    if code is None:
        return "Mixed skies"
    if code == 0:
        return "Clear"
    if code in (1, 2):
        return "Partly cloudy"
    if code == 3:
        return "Overcast"
    if code in (45, 48):
        return "Fog"
    if code in (51, 53, 55, 56, 57):
        return "Drizzle"
    if code in (61, 63, 65, 66, 67, 80, 81, 82):
        return "Rain"
    if code in (71, 73, 75, 77, 85, 86):
        return "Snow"
    if code in (95, 96, 99):
        return "Thunderstorm"
    return "Mixed skies"


def breeze_label(wind_kmh: float | None) -> str | None:
    if wind_kmh is None or not math.isfinite(wind_kmh):
        return None
    if wind_kmh < 8:
        return "still air"
    if wind_kmh < 20:
        return "light breeze"
    if wind_kmh < 40:
        return "breezy"
    return "windy"


def weather_summary(weather: Weather) -> str:
    if not weather.available:
        return "Weather unavailable · using the time of day"
    parts = [
        format_temp(weather.temp_c),
        condition_label(weather.weather_code),
        breeze_label(weather.wind_kmh),
    ]
    return " · ".join(part for part in parts if part)


def daypart(hour: int) -> str:
    if hour < 5 or hour >= 21:
        return "late"
    if hour < 11:
        return "morning"
    if hour < 14:
        return "midday"
    if hour < 17:
        return "afternoon"
    return "evening"


def _seed(*parts: int) -> int:
    value = 0
    for part in parts:
        value = (value * 31 + (int(part) & 0xFFFF)) & 0xFFFFFFFF
    return value


def classify(weather: Weather) -> str:
    if not weather.available:
        return "unknown"
    code = weather.weather_code if weather.weather_code is not None else -1
    precip = weather.precip_mm or 0
    temp = weather.temp_c
    wind = weather.wind_kmh or 0
    if code in (95, 96, 99):
        return "storm"
    if code in (71, 73, 75, 77, 85, 86):
        return "snow"
    if code in (51, 53, 55, 56, 57, 61, 63, 65, 66, 67, 80, 81, 82) or precip >= 0.5:
        return "rain"
    # After dark, stay on lit streets even when the air is also cold or windy.
    night = weather.is_day is False or weather.hour >= 21 or weather.hour < 6
    if night:
        return "night"
    if temp is not None and temp >= 29:
        return "hot"
    if temp is not None and temp <= 3:
        return "cold"
    if wind >= 40:
        return "wind"
    if code in (0, 1, 2) and weather.hour in (6, 7, 8, 16, 17, 18, 19):
        return "golden"
    if code in (3, 45, 48):
        return "gray"
    return "fair"


def _minutes_phrase(minutes: int) -> str:
    words = {
        8: "eight",
        12: "twelve",
        15: "fifteen",
        18: "eighteen",
        20: "twenty",
        22: "twenty-two",
        25: "twenty-five",
        30: "thirty",
    }
    return words.get(minutes, str(minutes))


def _why(kind: str, scene: Scene, minutes: int) -> str:
    spot = scene.spots[0].name if scene.spots else None
    span = _minutes_phrase(minutes)
    part = daypart(scene.weather.hour)
    temp = format_temp(scene.weather.temp_c)
    code = scene.weather.weather_code or 0
    variant = _seed(scene.weather.hour, code, minutes) % 2

    if kind == "storm":
        return f"Thunder is in the mix. {span.capitalize()} minutes close by, and turn back if it opens up."
    if kind == "rain":
        if variant == 0:
            return f"Rain is falling, so make it {span} minutes and stay near cover."
        return f"It's wet out. {span.capitalize()} minutes is enough, and turning around is part of the plan."
    if kind == "snow":
        return f"Snow changes the pace. Give it {span} unhurried minutes and watch your footing."
    if kind == "hot":
        if spot and variant == 1:
            return f"It's {temp}. Find shade near {spot} and keep the walk to {span} minutes."
        return f"It's {temp}. {span.capitalize()} minutes in the shade is the walk that fits."
    if kind == "cold":
        return f"The air is {temp}. A brisk {span} minutes, then back in."
    if kind == "wind":
        return f"The wind is up. Use side streets and keep it to {span} minutes."
    if kind == "night":
        if temp and scene.weather.temp_c is not None and scene.weather.temp_c <= 3:
            return f"It's late and the air is {temp}. {span.capitalize()} minutes on lit streets, then back in."
        return f"It's late. Stay on lit streets for {span} minutes and skip empty paths."
    if kind == "unknown":
        if scene.weather.hour >= 21 or scene.weather.hour < 6:
            return "The forecast didn't load. Fifteen lit minutes still counts."
        return "The forecast didn't load. Twenty easy minutes outside still counts."
    if kind == "golden":
        if spot:
            return f"The light is low and {spot} is close. This is the half hour to be outside."
        return "The light is low and the weather is kind. This is the half hour to be outside."
    if kind == "gray":
        if spot and variant == 0:
            return f"The sky is flat, which is a fine time to walk. {span.capitalize()} easy minutes toward {spot}."
        return f"The sky is flat, which is a fine time to walk without squinting. {span.capitalize()} minutes, easy pace."
    if spot and part == "morning":
        return f"{spot} is close, and the morning is mild enough for {span} easy minutes."
    if spot and variant == 1:
        return f"{spot} is nearby and the weather is ordinary in the best way. {span.capitalize()} minutes, then carry on."
    if part == "midday":
        return f"Midday is bright and usable. {span.capitalize()} minutes outside, then back to the day."
    return f"Conditions are ordinary in the best way. {span.capitalize()} minutes outside, then carry on."


def offline_cue(scene: Scene) -> Cue:
    kind = classify(scene.weather)
    minutes = DURATIONS[kind]
    vibe_kind = kind
    if kind == "unknown" and (scene.weather.hour >= 21 or scene.weather.hour < 6):
        minutes = DURATIONS["night"]
        vibe_kind = "night"
    options = VIBES[vibe_kind]
    vibe = options[_seed(scene.weather.hour, scene.weather.minute, minutes) % len(options)]
    return Cue(
        duration_minutes=minutes,
        vibe=vibe,
        why_now=_why(kind, scene, minutes),
        source="mock",
        notice=None,
        model=None,
    )


def parse_model_cue(text: str, model: str) -> Cue | None:
    """Pull one cue out of a model reply. None means the reply is unusable."""
    raw = text.strip()
    if raw.startswith("```"):
        raw = re.sub(r"^```(?:json)?\s*", "", raw, flags=re.IGNORECASE)
        raw = re.sub(r"\s*```$", "", raw)
    start = raw.find("{")
    end = raw.rfind("}")
    if start < 0 or end <= start:
        return None
    import json

    try:
        data = json.loads(raw[start : end + 1])
    except json.JSONDecodeError:
        return None
    if not isinstance(data, dict):
        return None
    try:
        minutes = int(data.get("duration_minutes"))
    except (TypeError, ValueError):
        return None
    minutes = max(8, min(40, minutes))
    vibe = _clean_vibe(data.get("vibe"))
    why = _clean_why(data.get("why_now"))
    if not vibe or not why:
        return None
    return Cue(
        duration_minutes=minutes,
        vibe=vibe,
        why_now=why,
        source="model",
        notice=None,
        model=model,
    )


def _clean_vibe(value: object) -> str | None:
    if not isinstance(value, str):
        return None
    text = " ".join(value.replace(".", " ").split()).strip(" \"'`")
    if not text:
        return None
    if len(text) > 60:
        text = text[:60].rsplit(" ", 1)[0].strip()
    return text.lower() or None


def _clean_why(value: object) -> str | None:
    if not isinstance(value, str):
        return None
    text = " ".join(value.split()).strip()
    if len(text) < 12:
        return None
    if len(text) > 240:
        text = text[:240].rsplit(" ", 1)[0].rstrip(" ,;:") + "."
    if text[-1] not in ".!?":
        text += "."
    return text


def public_spot(spot: Spot) -> dict[str, object]:
    return {
        "name": spot.name,
        "distance": format_distance(spot.distance_m),
        "sample": spot.sample,
    }


def chat_completions_url(base_url: str) -> str:
    base = base_url.strip().rstrip("/")
    if base.endswith("/chat/completions"):
        return base
    if base.endswith("/v1"):
        return base + "/chat/completions"
    return base + "/v1/chat/completions"
