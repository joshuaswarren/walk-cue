"""Build one walk from a typed area. The area is not stored."""

from __future__ import annotations

import asyncio
import time
from datetime import datetime

import httpx

from walkcue.config import Settings
from walkcue.cue import CueWriter
from walkcue.models import Cue, Place, Scene, Spot, Weather
from walkcue.phrasing import (
    condition_label,
    client_now,
    is_placeholder,
    local_clock,
    normalize_area,
    public_spot,
    uses_imperial,
    weather_summary,
)
from walkcue.upstream import Upstream

SAMPLE_NOTE = "Sample spots for the Anytown placeholder, not a map search."
SAMPLE_SPOTS = (
    Spot("North Meadow", 420, sample=True),
    Spot("Canal Path", 980, sample=True),
    Spot("Little Hill", 1500, sample=True),
)


class SceneCache:
    def __init__(self, ttl_seconds: float = 600, limit: int = 32) -> None:
        self._ttl = ttl_seconds
        self._limit = limit
        self._items: dict[str, tuple[float, Scene]] = {}

    def get(self, key: str) -> Scene | None:
        item = self._items.get(key)
        if item is None:
            return None
        saved_at, scene = item
        if time.monotonic() - saved_at > self._ttl:
            self._items.pop(key, None)
            return None
        return scene

    def put(self, key: str, scene: Scene) -> None:
        self._items[key] = (time.monotonic(), scene)
        if len(self._items) <= self._limit:
            return
        oldest = min(self._items, key=lambda name: self._items[name][0])
        self._items.pop(oldest, None)


def placeholder_scene(query: str, now: datetime | None = None) -> Scene:
    """Anytown is fictional on purpose so a demo never needs a real place."""
    hour, minute, local_time = local_clock(now)
    is_day = 6 <= hour < 20
    return Scene(
        place=Place(
            query=query,
            label="Anytown",
            latitude=0.0,
            longitude=0.0,
            country_code=None,
            demo=True,
        ),
        weather=Weather(
            available=True,
            temp_c=17.5,
            weather_code=1,
            wind_kmh=12.0,
            precip_mm=0.0,
            is_day=is_day,
            local_time=local_time,
            hour=hour,
            minute=minute,
        ),
        spots=SAMPLE_SPOTS,
        spots_note=SAMPLE_NOTE,
    )


class WalkService:
    def __init__(self, client: httpx.AsyncClient, settings: Settings) -> None:
        self._upstream = Upstream(client)
        self._cues = CueWriter(client, settings)
        self._cache = SceneCache()

    async def compose(self, area: str, local_time: str | None = None) -> dict[str, object]:
        query = normalize_area(area)
        if is_placeholder(query):
            scene = placeholder_scene(query, now=client_now(local_time))
        else:
            scene = await self._scene(query)
        cue = await self._cues.write(scene)
        return _public(scene, cue)

    async def _scene(self, query: str) -> Scene:
        key = query.casefold()
        cached = self._cache.get(key)
        if cached is not None:
            return cached
        place = await self._upstream.geocode(query)
        weather, spot_result = await asyncio.gather(
            self._upstream.weather(place),
            self._upstream.spots(place),
        )
        spots, note = spot_result
        scene = Scene(place=place, weather=weather, spots=spots, spots_note=note)
        if weather.available:
            self._cache.put(key, scene)
        return scene


def _public(scene: Scene, cue: Cue) -> dict[str, object]:
    imperial = uses_imperial(scene.place.country_code)
    condition = condition_label(scene.weather.weather_code) if scene.weather.available else None
    return {
        "area": {
            "query": scene.place.query,
            "label": scene.place.label,
            "demo": scene.place.demo,
        },
        "weather": {
            "available": scene.weather.available,
            "summary": weather_summary(scene.weather, imperial),
            "condition": condition,
            "local_time": scene.weather.local_time,
        },
        "cue": {
            "duration_minutes": cue.duration_minutes,
            "vibe": cue.vibe,
            "why_now": cue.why_now,
            "source": cue.source,
            "notice": cue.notice,
            "model": cue.model,
        },
        "spots": [public_spot(spot, imperial) for spot in scene.spots],
        "spots_note": scene.spots_note,
    }
