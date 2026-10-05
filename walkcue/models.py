"""Values that move from weather and maps into one walk cue."""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class Place:
    query: str
    label: str
    latitude: float
    longitude: float
    country_code: str | None
    demo: bool


@dataclass(frozen=True)
class Weather:
    available: bool
    temp_c: float | None
    weather_code: int | None
    wind_kmh: float | None
    precip_mm: float | None
    is_day: bool | None
    local_time: str
    hour: int
    minute: int


@dataclass(frozen=True)
class Spot:
    name: str
    distance_m: int
    sample: bool = False


@dataclass(frozen=True)
class Scene:
    place: Place
    weather: Weather
    spots: tuple[Spot, ...]
    spots_note: str | None


@dataclass(frozen=True)
class Cue:
    duration_minutes: int
    vibe: str
    why_now: str
    source: str
    notice: str | None
    model: str | None
