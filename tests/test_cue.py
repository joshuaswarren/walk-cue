import asyncio
import json
import logging
from dataclasses import replace

import httpx
import pytest

from walkcue.config import Settings
from walkcue.cue import CueWriter
from walkcue.models import Place, Scene, Weather

SCENE = Scene(
    place=Place(
        query="Lisbon",
        label="Lisbon, Portugal",
        latitude=38.7223,
        longitude=-9.1393,
        country_code="PT",
        demo=False,
    ),
    weather=Weather(
        available=True,
        temp_c=18.0,
        weather_code=1,
        wind_kmh=6.0,
        precip_mm=0.0,
        is_day=True,
        local_time="14:00",
        hour=14,
        minute=0,
    ),
    spots=(),
    spots_note=None,
)

MODEL_REPLY = {
    "choices": [
        {
            "message": {
                "content": (
                    '{"duration_minutes": 20, "vibe": "easy shaded loop", '
                    '"why_now": "It is mild and bright enough for a short loop."}'
                )
            }
        }
    ]
}


@pytest.fixture
def live(settings: Settings) -> Settings:
    return replace(settings, llm_mode="live", llm_base_url="http://llm.test/v1")


def _write(settings: Settings, handler) -> tuple:
    sent: list[dict] = []

    def recording(request: httpx.Request) -> httpx.Response:
        sent.append(json.loads(request.content.decode()))
        return handler(request)

    async def run():
        async with httpx.AsyncClient(transport=httpx.MockTransport(recording)) as client:
            return await CueWriter(client, settings).write(SCENE)

    return asyncio.run(run()), sent


def test_chat_template_kwargs_are_sent_by_default(live: Settings):
    cue, sent = _write(live, lambda _: httpx.Response(200, json=MODEL_REPLY))
    assert cue.source == "model"
    assert sent[0]["chat_template_kwargs"] == {"enable_thinking": False}


def test_chat_template_kwargs_can_be_turned_off_for_strict_servers(live: Settings):
    strict = replace(live, llm_chat_template_kwargs=False)

    def handler(request: httpx.Request) -> httpx.Response:
        # A strict OpenAI-compatible server rejects fields it does not know.
        if "chat_template_kwargs" in json.loads(request.content.decode()):
            return httpx.Response(400, json={"error": "unknown field chat_template_kwargs"})
        return httpx.Response(200, json=MODEL_REPLY)

    cue, sent = _write(strict, handler)
    assert "chat_template_kwargs" not in sent[0]
    assert cue.source == "model"


def test_chat_template_kwargs_env_flag(monkeypatch: pytest.MonkeyPatch):
    monkeypatch.delenv("WALK_CUE_LLM_CHAT_TEMPLATE_KWARGS", raising=False)
    assert Settings.from_env().llm_chat_template_kwargs is True
    for off in ("0", "false", "No", "off"):
        monkeypatch.setenv("WALK_CUE_LLM_CHAT_TEMPLATE_KWARGS", off)
        assert Settings.from_env().llm_chat_template_kwargs is False
    monkeypatch.setenv("WALK_CUE_LLM_CHAT_TEMPLATE_KWARGS", "1")
    assert Settings.from_env().llm_chat_template_kwargs is True


@pytest.mark.parametrize(
    ("handler", "reason"),
    [
        (lambda _: httpx.Response(400, json={"error": "bad request"}), "HTTP 400"),
        (lambda request: (_ for _ in ()).throw(httpx.ConnectError("refused", request=request)), "ConnectError"),
        (lambda _: httpx.Response(200, text="not json"), "invalid JSON"),
        (lambda _: httpx.Response(200, json={"choices": [{"message": {"content": "hi"}}]}), "unparsable"),
    ],
)
def test_fallback_logs_why_the_model_was_not_used(
    live: Settings, caplog: pytest.LogCaptureFixture, handler, reason: str
):
    with caplog.at_level(logging.WARNING, logger="walkcue.cue"):
        cue, _ = _write(live, handler)
    assert cue.source == "mock"
    warnings = [record.getMessage() for record in caplog.records if record.levelno == logging.WARNING]
    assert len(warnings) == 1, warnings
    assert reason in warnings[0]
    assert "gemma3" in warnings[0]


def test_a_model_cue_logs_nothing(live: Settings, caplog: pytest.LogCaptureFixture):
    with caplog.at_level(logging.WARNING, logger="walkcue.cue"):
        cue, _ = _write(live, lambda _: httpx.Response(200, json=MODEL_REPLY))
    assert cue.source == "model"
    assert caplog.records == []
