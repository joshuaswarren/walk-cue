"""Ask a local OpenAI-compatible model, or write the cue offline."""

from __future__ import annotations

from typing import Any

import httpx

from walkcue.config import Settings
from walkcue.models import Cue, Scene
from walkcue.phrasing import (
    chat_completions_url,
    daypart,
    offline_cue,
    parse_model_cue,
    weather_summary,
)

SYSTEM_PROMPT = """You suggest one short outdoor walk the reader can start immediately.
Reply with JSON only, no markdown, in this shape:
{"duration_minutes": 20, "vibe": "easy shaded loop", "why_now": "One concrete sentence."}

Rules:
- duration_minutes is an integer from 8 to 40.
- vibe is 2 to 6 words, lowercase, no period.
- why_now is one sentence, under 220 characters, tied to the weather and the time of day.
- Mention a nearby spot only if one is listed and it genuinely fits.
- Do not invent addresses or places you were not given.
- Use American units only: temperatures in °F, distances in miles or feet. Never °C, kilometers, or meters.
- No emoji, hashtags, or pep talk.
"""

FALLBACK_NOTICE = "The model didn't answer, so this is the offline cue."


def prompt_for(scene: Scene) -> str:
    if scene.spots:
        spots = "\n".join(f"- {spot.name}" for spot in scene.spots)
    else:
        spots = "none found"
    return (
        f"Area: {scene.place.label}\n"
        f"Local time: {scene.weather.local_time} ({daypart(scene.weather.hour)})\n"
        f"Weather: {weather_summary(scene.weather)}\n"
        f"Nearby outdoor spots:\n{spots}\n"
    )


def _content_string(content: object) -> str:
    if isinstance(content, str):
        return content
    if isinstance(content, list):
        parts: list[str] = []
        for item in content:
            if isinstance(item, dict) and isinstance(item.get("text"), str):
                parts.append(item["text"])
        return "\n".join(parts)
    return ""


def _message_text(payload: dict[str, Any]) -> str:
    choices = payload.get("choices") or []
    if not choices or not isinstance(choices, list):
        return ""
    first = choices[0] if isinstance(choices[0], dict) else {}
    message = first.get("message") if isinstance(first, dict) else {}
    if not isinstance(message, dict):
        return ""
    text = _content_string(message.get("content"))
    if text.strip():
        return text
    # Qwen3 thinking templates leave content empty and put the reply in
    # reasoning_content unless the request disables thinking.
    reasoning = message.get("reasoning_content")
    if isinstance(reasoning, str) and reasoning.strip():
        return reasoning
    return text


class CueWriter:
    def __init__(self, client: httpx.AsyncClient, settings: Settings) -> None:
        self._client = client
        self._settings = settings

    async def write(self, scene: Scene) -> Cue:
        if not self._settings.live:
            return offline_cue(scene)
        try:
            text = await self._complete(prompt_for(scene))
        except (httpx.HTTPError, ValueError):
            return _fallback(scene)
        parsed = parse_model_cue(text, self._settings.llm_model)
        if parsed is None:
            return _fallback(scene)
        return parsed

    async def _complete(self, user_prompt: str) -> str:
        headers = {"Content-Type": "application/json"}
        if self._settings.llm_api_key:
            headers["Authorization"] = f"Bearer {self._settings.llm_api_key}"
        response = await self._client.post(
            chat_completions_url(self._settings.llm_base_url),
            json={
                "model": self._settings.llm_model,
                "temperature": 0.3,
                "max_tokens": 300,
                "messages": [
                    {"role": "system", "content": SYSTEM_PROMPT},
                    {"role": "user", "content": user_prompt},
                ],
                # Qwen3 chat templates think by default and then return empty
                # content. llama-server honors this and writes the cue instead.
                "chat_template_kwargs": {"enable_thinking": False},
            },
            headers=headers,
            timeout=httpx.Timeout(self._settings.llm_timeout, connect=3.0),
        )
        response.raise_for_status()
        payload = response.json()
        if not isinstance(payload, dict):
            return ""
        return _message_text(payload)


def _fallback(scene: Scene) -> Cue:
    cue = offline_cue(scene)
    return Cue(
        duration_minutes=cue.duration_minutes,
        vibe=cue.vibe,
        why_now=cue.why_now,
        source="mock",
        notice=FALLBACK_NOTICE,
        model=None,
    )
