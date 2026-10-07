import json

import httpx
from fastapi.testclient import TestClient

from walkcue.config import Settings
from walkcue.main import create_app


LISBON = {
    "results": [
        {
            "name": "Lisbon",
            "latitude": 38.7223,
            "longitude": -9.1393,
            "country_code": "PT",
            "country": "Portugal",
            "admin1": "Lisbon",
        }
    ]
}

SPRINGFIELD = {
    "results": [
        {
            "name": "Springfield",
            "latitude": 39.7817,
            "longitude": -89.6501,
            "country_code": "US",
            "country": "United States",
            "admin1": "Illinois",
        }
    ]
}


def _forecast(code: int, temp: float, hour: str = "2026-10-05T10:00") -> dict:
    return {
        "current": {
            "time": hour,
            "temperature_2m": temp,
            "weather_code": code,
            "wind_speed_10m": 6,
            "precipitation": 0,
            "is_day": 1,
        }
    }


def _parks() -> dict:
    return {
        "elements": [
            {
                "type": "way",
                "tags": {"name": "City Park", "leisure": "park"},
                "center": {"lat": 38.73, "lon": -9.15},
            },
            {
                "type": "node",
                "tags": {"name": "City Park", "leisure": "park"},
                "lat": 38.74,
                "lon": -9.16,
            },
            {
                "type": "node",
                "tags": {"name": "River Garden", "leisure": "garden"},
                "lat": 38.71,
                "lon": -9.14,
            },
        ]
    }


def _client(settings: Settings, handler):
    app = create_app(settings, transport=httpx.MockTransport(handler))
    return TestClient(app)


def test_health_and_page_are_a_single_card(settings: Settings):
    def handler(request: httpx.Request) -> httpx.Response:
        raise AssertionError(f"unexpected call {request.url}")

    with _client(settings, handler) as client:
        health = client.get("/api/health")
        assert health.status_code == 200
        assert health.json() == {"ok": True, "llm_mode": "mock"}
        page = client.get("/")
        assert page.status_code == 200
        assert "Go walk" in page.text
        assert "Anytown" in page.text
        assert "dashboard" not in page.text.lower()
        assert client.get("/static/styles.css").status_code == 200
        assert client.get("/static/app.js").status_code == 200


def test_anytown_skips_the_network(settings: Settings):
    def handler(request: httpx.Request) -> httpx.Response:
        raise AssertionError(f"placeholder should stay local, called {request.url}")

    with _client(settings, handler) as client:
        response = client.post("/api/cue", json={"area": "Anytown"})
        assert response.status_code == 200
        body = response.json()
        assert body["area"]["demo"] is True
        assert body["area"]["label"] == "Anytown"
        assert body["cue"]["source"] == "mock"
        assert body["cue"]["notice"] is None
        assert [spot["name"] for spot in body["spots"]] == [
            "North Meadow",
            "Canal Path",
            "Little Hill",
        ]
        assert "not a map search" in body["spots_note"]
        assert body["weather"]["summary"].startswith("64°F")
        assert "°C" not in body["weather"]["summary"]
        assert [spot["distance"] for spot in body["spots"]] == ["0.3 mi", "0.6 mi", "0.9 mi"]
        assert "latitude" not in response.text

        morning = client.post("/api/cue", json={"area": "Anytown", "local_time": "07:30"})
        assert morning.status_code == 200
        assert morning.json()["weather"]["local_time"] == "07:30"
        assert morning.json()["cue"]["duration_minutes"] == 30

        late = client.get("/api/cue", params={"area": "Anytown", "local_time": "22:10"})
        assert late.status_code == 200
        assert late.json()["cue"]["duration_minutes"] == 15


def test_real_place_uses_weather_and_parks_without_a_model(settings: Settings):
    calls: list[str] = []

    def handler(request: httpx.Request) -> httpx.Response:
        calls.append(request.url.host)
        if request.url.host == "geocoding-api.open-meteo.com":
            name = request.url.params["name"]
            payload = SPRINGFIELD if name == "Springfield" else LISBON
            return httpx.Response(200, json=payload)
        if request.url.host == "api.open-meteo.com":
            return httpx.Response(200, json=_forecast(0, 20))
        if request.url.host == "overpass-api.de":
            return httpx.Response(
                200,
                json={
                    "elements": [
                        {
                            "type": "node",
                            "tags": {"name": "City Park", "leisure": "park"},
                            "lat": 39.786,
                            "lon": -89.644,
                        },
                        {
                            "type": "node",
                            "tags": {"name": "City Park", "leisure": "park"},
                            "lat": 39.80,
                            "lon": -89.67,
                        },
                        {
                            "type": "way",
                            "tags": {"name": "River Garden", "leisure": "garden"},
                            "center": {"lat": 39.775, "lon": -89.655},
                        },
                    ]
                },
            )
        if request.url.path.endswith("/chat/completions"):
            raise AssertionError("mock mode must not call a model")
        return httpx.Response(404)

    with _client(settings, handler) as client:
        first = client.post("/api/cue", json={"area": "Springfield"})
        assert first.status_code == 200
        body = first.json()
        assert body["area"]["label"] == "Springfield, Illinois, United States"
        assert body["weather"]["summary"].startswith("68°F")
        assert body["cue"]["source"] == "mock"
        assert body["cue"]["duration_minutes"] == 25
        assert body["spots"][0]["distance"].endswith("mi")
        assert "City Park" in {spot["name"] for spot in body["spots"]}
        assert len([spot for spot in body["spots"] if spot["name"] == "City Park"]) == 1

        second = client.post("/api/cue", json={"area": "Springfield"})
        assert second.status_code == 200

    assert calls.count("geocoding-api.open-meteo.com") == 1
    assert "llm.test" not in calls


def test_live_model_writes_the_cue_and_falls_back(settings: Settings):
    live = Settings(
        llm_mode="live",
        llm_base_url="http://llm.test/v1",
        llm_model="gemma3",
        llm_api_key="test-token",
        llm_timeout=5,
        host="127.0.0.1",
        port=8000,
    )
    mode = {"llm": "ok"}

    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.host == "geocoding-api.open-meteo.com":
            return httpx.Response(200, json=LISBON)
        if request.url.host == "api.open-meteo.com":
            return httpx.Response(200, json=_forecast(61, 12, "2026-10-05T15:00"))
        if request.url.host == "overpass-api.de":
            return httpx.Response(200, json={"elements": []})
        if request.url.host == "nominatim.openstreetmap.org":
            return httpx.Response(
                200,
                json=[
                    {
                        "name": "Hill Park",
                        "lat": "38.73",
                        "lon": "-9.15",
                    }
                ],
            )
        if request.url.host == "llm.test":
            assert request.headers["authorization"] == "Bearer test-token"
            sent = json.loads(request.content.decode())
            assert sent["model"] == "gemma3"
            user = sent["messages"][1]["content"]
            assert "Lisbon" in user
            assert "latitude" not in user
            if mode["llm"] == "down":
                return httpx.Response(503, json={"error": "down"})
            return httpx.Response(
                200,
                json={
                    "choices": [
                        {
                            "message": {
                                "content": (
                                    '{"duration_minutes": 18, "vibe": "quiet river loop", '
                                    '"why_now": "The rain is light enough for a short loop."}'
                                )
                            }
                        }
                    ]
                },
            )
        return httpx.Response(404)

    with _client(live, handler) as client:
        live_cue = client.get("/api/cue", params={"area": "Lisbon"})
        assert live_cue.status_code == 200
        body = live_cue.json()
        assert body["cue"]["source"] == "model"
        assert body["cue"]["model"] == "gemma3"
        assert body["weather"]["summary"].startswith("54°F")
        assert "°C" not in body["weather"]["summary"]
        assert "km" not in live_cue.text
        for spot in body["spots"]:
            assert spot["distance"].endswith(("mi", "ft")) or spot["distance"] == "nearby"
        assert body["cue"]["duration_minutes"] == 18
        assert body["cue"]["vibe"] == "quiet river loop"
        assert any(spot["name"] == "Hill Park" for spot in body["spots"])

        mode["llm"] = "down"
        fallback = client.post("/api/cue", json={"area": "  Lisbon "})
        assert fallback.status_code == 200
        offline = fallback.json()["cue"]
        assert offline["source"] == "mock"
        assert offline["notice"]
        assert offline["duration_minutes"] == 12


def test_missing_place_and_bad_input(settings: Settings):
    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.host == "geocoding-api.open-meteo.com":
            return httpx.Response(200, json={"results": []})
        return httpx.Response(404)

    with _client(settings, handler) as client:
        missing = client.post("/api/cue", json={"area": "Nowhereville"})
        assert missing.status_code == 404
        rejected = client.post("/api/cue", json={"area": "!!!"})
        assert rejected.status_code == 400


def test_weather_outage_still_returns_a_cue(settings: Settings):
    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.host == "geocoding-api.open-meteo.com":
            return httpx.Response(200, json=LISBON)
        if request.url.host == "api.open-meteo.com":
            return httpx.Response(503)
        if request.url.host == "overpass-api.de":
            return httpx.Response(504)
        if request.url.host == "nominatim.openstreetmap.org":
            return httpx.Response(429)
        return httpx.Response(404)

    with _client(settings, handler) as client:
        response = client.post("/api/cue", json={"area": "Lisbon"})
        assert response.status_code == 200
        body = response.json()
        assert body["weather"]["available"] is False
        assert body["cue"]["source"] == "mock"
        assert body["spots"] == []
        assert body["spots_note"]
