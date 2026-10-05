"""Open-Meteo for weather, Overpass then Nominatim for nearby outdoor spots."""

from __future__ import annotations

import math
from typing import Any

import httpx

from walkcue.models import Place, Spot, Weather
from walkcue.phrasing import AreaNotFound, UpstreamError, local_clock

GEOCODE_URL = "https://geocoding-api.open-meteo.com/v1/search"
FORECAST_URL = "https://api.open-meteo.com/v1/forecast"
OVERPASS_URL = "https://overpass-api.de/api/interpreter"
NOMINATIM_URL = "https://nominatim.openstreetmap.org/search"

OSM_HEADERS = {"Accept": "application/json"}


def _finite(value: object, low: float, high: float) -> float | None:
    try:
        number = float(value)  # type: ignore[arg-type]
    except (TypeError, ValueError):
        return None
    if not math.isfinite(number) or number < low or number > high:
        return None
    return number


def _clock_from_iso(value: object) -> tuple[int, int, str] | None:
    if not isinstance(value, str) or "T" not in value:
        return None
    clock = value.split("T", 1)[1]
    parts = clock.split(":")
    if len(parts) < 2:
        return None
    try:
        hour = int(parts[0])
        minute = int(parts[1])
    except ValueError:
        return None
    if not (0 <= hour <= 23 and 0 <= minute <= 59):
        return None
    return hour, minute, f"{hour:02d}:{minute:02d}"


def place_from_geocode(payload: dict[str, Any], query: str) -> Place:
    results = payload.get("results") or []
    if not results:
        raise AreaNotFound("No place matched that. Try a city name or a postal code.")
    row = results[0]
    lat = _finite(row.get("latitude"), -90, 90)
    lon = _finite(row.get("longitude"), -180, 180)
    if lat is None or lon is None:
        raise UpstreamError("The place lookup came back without coordinates.")
    name = str(row.get("name") or query)
    admin = str(row.get("admin1") or "")
    country = str(row.get("country") or "")
    parts = [name]
    if admin and admin.casefold() != name.casefold():
        parts.append(admin)
    if country and all(country.casefold() != part.casefold() for part in parts):
        parts.append(country)
    country_code = row.get("country_code")
    code = str(country_code).upper() if country_code else None
    return Place(
        query=query,
        label=", ".join(parts),
        latitude=lat,
        longitude=lon,
        country_code=code,
        demo=False,
    )


def weather_from_forecast(payload: dict[str, Any]) -> Weather:
    current = payload.get("current") or {}
    clock = _clock_from_iso(current.get("time"))
    if clock is None:
        hour, minute, local_time = local_clock()
    else:
        hour, minute, local_time = clock
    is_day_raw = current.get("is_day")
    is_day: bool | None
    if is_day_raw in (0, 1, True, False):
        is_day = bool(is_day_raw)
    else:
        is_day = None
    code = current.get("weather_code")
    weather_code = int(code) if isinstance(code, int | float) and not isinstance(code, bool) else None
    return Weather(
        available=True,
        temp_c=_finite(current.get("temperature_2m"), -80, 60),
        weather_code=weather_code,
        wind_kmh=_finite(current.get("wind_speed_10m"), 0, 300),
        precip_mm=_finite(current.get("precipitation"), 0, 500),
        is_day=is_day,
        local_time=local_time,
        hour=hour,
        minute=minute,
    )


def unavailable_weather() -> Weather:
    hour, minute, local_time = local_clock()
    return Weather(
        available=False,
        temp_c=None,
        weather_code=None,
        wind_kmh=None,
        precip_mm=None,
        is_day=None,
        local_time=local_time,
        hour=hour,
        minute=minute,
    )


def haversine_m(lat1: float, lon1: float, lat2: float, lon2: float) -> float:
    radius = 6_371_000
    phi1, phi2 = math.radians(lat1), math.radians(lat2)
    dphi = math.radians(lat2 - lat1)
    dlambda = math.radians(lon2 - lon1)
    a = math.sin(dphi / 2) ** 2 + math.cos(phi1) * math.cos(phi2) * math.sin(dlambda / 2) ** 2
    return 2 * radius * math.asin(math.sqrt(a))


def _nearest(candidates: list[Spot]) -> tuple[Spot, ...]:
    unique: dict[str, Spot] = {}
    for spot in candidates:
        key = spot.name.casefold()
        current = unique.get(key)
        if current is None or spot.distance_m < current.distance_m:
            unique[key] = spot
    ranked = sorted(unique.values(), key=lambda spot: spot.distance_m)
    return tuple(ranked[:3])


def spots_from_overpass(payload: dict[str, Any], latitude: float, longitude: float) -> tuple[Spot, ...]:
    found: list[Spot] = []
    for element in payload.get("elements") or []:
        if not isinstance(element, dict):
            continue
        tags = element.get("tags") or {}
        name = tags.get("name")
        if not isinstance(name, str) or not name.strip():
            continue
        lat = _finite(element.get("lat"), -90, 90)
        lon = _finite(element.get("lon"), -180, 180)
        if lat is None or lon is None:
            center = element.get("center") or {}
            lat = _finite(center.get("lat"), -90, 90)
            lon = _finite(center.get("lon"), -180, 180)
        if lat is None or lon is None:
            continue
        distance = int(round(haversine_m(latitude, longitude, lat, lon)))
        if distance > 12_000:
            continue
        found.append(Spot(name=name.strip(), distance_m=distance))
    return _nearest(found)


def spots_from_nominatim(payload: object, latitude: float, longitude: float) -> tuple[Spot, ...]:
    rows = payload if isinstance(payload, list) else []
    found: list[Spot] = []
    for row in rows:
        if not isinstance(row, dict):
            continue
        name = row.get("name") or ""
        if not isinstance(name, str) or not name.strip():
            display = str(row.get("display_name") or "")
            name = display.split(",", 1)[0].strip()
        if not name:
            continue
        lat = _finite(row.get("lat"), -90, 90)
        lon = _finite(row.get("lon"), -180, 180)
        if lat is None or lon is None:
            continue
        distance = int(round(haversine_m(latitude, longitude, lat, lon)))
        if distance > 12_000:
            continue
        found.append(Spot(name=name.strip(), distance_m=distance))
    return _nearest(found)


def overpass_query(latitude: float, longitude: float) -> str:
    lat = f"{latitude:.5f}"
    lon = f"{longitude:.5f}"
    return (
        "[out:json][timeout:8];\n"
        "(\n"
        f'  nwr["leisure"="park"]["name"](around:3500,{lat},{lon});\n'
        f'  nwr["leisure"="garden"]["name"](around:3500,{lat},{lon});\n'
        f'  nwr["leisure"="nature_reserve"]["name"](around:3500,{lat},{lon});\n'
        ");\n"
        "out center 25;\n"
    )


class Upstream:
    def __init__(self, client: httpx.AsyncClient) -> None:
        self._client = client

    async def geocode(self, query: str) -> Place:
        try:
            response = await self._client.get(
                GEOCODE_URL,
                params={"name": query, "count": 1, "language": "en", "format": "json"},
                timeout=6.0,
            )
            response.raise_for_status()
            payload = response.json()
        except (httpx.HTTPError, ValueError) as exc:
            raise UpstreamError("Could not reach the weather service. Try again in a moment.") from exc
        if not isinstance(payload, dict):
            raise UpstreamError("The place lookup returned something unexpected.")
        return place_from_geocode(payload, query)

    async def weather(self, place: Place) -> Weather:
        params = {
            "latitude": place.latitude,
            "longitude": place.longitude,
            "current": "temperature_2m,weather_code,wind_speed_10m,precipitation,is_day",
            "timezone": "auto",
            "forecast_days": 1,
            "wind_speed_unit": "kmh",
            "temperature_unit": "celsius",
        }
        try:
            response = await self._client.get(FORECAST_URL, params=params, timeout=6.0)
            response.raise_for_status()
            payload = response.json()
        except (httpx.HTTPError, ValueError):
            return unavailable_weather()
        if not isinstance(payload, dict) or "current" not in payload:
            return unavailable_weather()
        return weather_from_forecast(payload)

    async def spots(self, place: Place) -> tuple[tuple[Spot, ...], str | None]:
        try:
            response = await self._client.post(
                OVERPASS_URL,
                content=overpass_query(place.latitude, place.longitude),
                headers={"Content-Type": "text/plain", **OSM_HEADERS},
                timeout=8.0,
            )
            response.raise_for_status()
            payload = response.json()
        except (httpx.HTTPError, ValueError):
            payload = None
        overpass_ok = isinstance(payload, dict) and "elements" in payload
        if overpass_ok:
            spots = spots_from_overpass(payload, place.latitude, place.longitude)
            if spots:
                return spots, None

        nominatim = await self._nominatim(place)
        if nominatim:
            return nominatim, None
        if nominatim is None and not overpass_ok:
            return (), "Park search didn't answer. The walk cue still stands."
        return (), "No named parks turned up nearby."

    async def _nominatim(self, place: Place) -> tuple[Spot, ...] | None:
        # A small box around the point, left, top, right, bottom.
        delta_lat = 0.04
        delta_lon = 0.05
        viewbox = (
            f"{place.longitude - delta_lon:.5f},{place.latitude + delta_lat:.5f},"
            f"{place.longitude + delta_lon:.5f},{place.latitude - delta_lat:.5f}"
        )
        try:
            response = await self._client.get(
                NOMINATIM_URL,
                params={
                    "q": "park",
                    "format": "jsonv2",
                    "limit": 8,
                    "viewbox": viewbox,
                    "bounded": 1,
                },
                headers=OSM_HEADERS,
                timeout=6.0,
            )
            response.raise_for_status()
            payload = response.json()
        except (httpx.HTTPError, ValueError):
            return None
        return spots_from_nominatim(payload, place.latitude, place.longitude)
