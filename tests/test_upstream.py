import math

import pytest

from walkcue.phrasing import AreaNotFound, UpstreamError
from walkcue.upstream import (
    haversine_m,
    overpass_query,
    place_from_geocode,
    spots_from_nominatim,
    spots_from_overpass,
    weather_from_forecast,
)


def test_haversine_known_distances():
    assert haversine_m(38.7, -9.1, 38.7, -9.1) == 0
    # One degree of latitude on a 6,371 km sphere is about 111.19 km.
    assert math.isclose(haversine_m(0, 0, 1, 0), 111_194.9, rel_tol=1e-4)
    # Lisbon to Porto is about 274 km in a straight line.
    assert math.isclose(haversine_m(38.7223, -9.1393, 41.1579, -8.6291), 274_000, rel_tol=0.01)
    assert math.isclose(haversine_m(10, 20, 30, 40), haversine_m(30, 40, 10, 20))


def test_overpass_query_rounds_coordinates_and_asks_for_named_green_spaces():
    query = overpass_query(38.722345678, -9.139312345)
    assert query.startswith("[out:json][timeout:8];")
    assert query.rstrip().endswith("out center 25;")
    for leisure in ("park", "garden", "nature_reserve"):
        assert f'nwr["leisure"="{leisure}"]["name"](around:3500,38.72235,-9.13931);' in query
    assert "38.722345678" not in query


def test_spots_from_overpass_dedupes_ranks_and_drops_far_or_unnamed():
    payload = {
        "elements": [
            {"tags": {"name": "City Park"}, "center": {"lat": 38.73, "lon": -9.15}},
            {"tags": {"name": "city park"}, "lat": 38.7225, "lon": -9.1395},
            {"tags": {"name": "River Garden"}, "lat": 38.71, "lon": -9.14},
            {"tags": {"name": "Hill Reserve"}, "lat": 38.75, "lon": -9.13},
            {"tags": {"name": "Far Park"}, "lat": 39.5, "lon": -9.14},
            {"tags": {"name": "  "}, "lat": 38.72, "lon": -9.14},
            {"tags": {}, "lat": 38.72, "lon": -9.14},
            {"tags": {"name": "No Coordinates"}},
            "not an element",
        ]
    }
    spots = spots_from_overpass(payload, 38.7223, -9.1393)
    assert [spot.name for spot in spots] == ["city park", "River Garden", "Hill Reserve"]
    assert [spot.distance_m for spot in spots] == sorted(spot.distance_m for spot in spots)
    assert spots[0].distance_m < 50


def test_spots_from_nominatim_uses_display_name_and_ignores_bad_rows():
    payload = [
        {"name": "", "display_name": "Hill Park, Lisbon, Portugal", "lat": "38.73", "lon": "-9.15"},
        {"name": "Bad Row", "lat": "north", "lon": "-9.15"},
        "not a row",
    ]
    spots = spots_from_nominatim(payload, 38.7223, -9.1393)
    assert [spot.name for spot in spots] == ["Hill Park"]
    assert spots_from_nominatim({"not": "a list"}, 38.7, -9.1) == ()


def test_place_from_geocode_builds_the_label_and_rejects_bad_results():
    place = place_from_geocode(
        {
            "results": [
                {
                    "name": "Lisbon",
                    "latitude": 38.7223,
                    "longitude": -9.1393,
                    "country_code": "pt",
                    "country": "Portugal",
                    "admin1": "Lisbon",
                }
            ]
        },
        "lisbon",
    )
    assert place.label == "Lisbon, Portugal"
    assert place.country_code == "PT"
    assert (place.latitude, place.longitude) == (38.7223, -9.1393)
    assert place.demo is False

    with pytest.raises(AreaNotFound):
        place_from_geocode({"results": []}, "nowhere")
    with pytest.raises(UpstreamError):
        place_from_geocode({"results": [{"name": "Broken", "latitude": 200, "longitude": 0}]}, "broken")


def test_weather_from_forecast_reads_the_local_clock_and_drops_out_of_range_values():
    weather = weather_from_forecast(
        {
            "current": {
                "time": "2026-10-05T15:07",
                "temperature_2m": 12.5,
                "weather_code": 61,
                "wind_speed_10m": 999,
                "precipitation": -1,
                "is_day": 0,
            }
        }
    )
    assert (weather.hour, weather.minute, weather.local_time) == (15, 7, "15:07")
    assert weather.temp_c == 12.5
    assert weather.weather_code == 61
    assert weather.wind_kmh is None
    assert weather.precip_mm is None
    assert weather.is_day is False
    assert weather.available is True
