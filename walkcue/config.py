"""Runtime settings. The area someone walks from is not one of them."""

from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path

USER_AGENT = "WalkCue/1.0 (local outdoor walk cue; +https://github.com/joshuaswarren/walk-cue)"


def _apply_env_file(path: Path) -> None:
    for raw in path.read_text(encoding="utf-8").splitlines():
        line = raw.strip()
        if not line or line.startswith("#"):
            continue
        if line.startswith("export "):
            line = line[len("export ") :].strip()
        if "=" not in line:
            continue
        key, value = line.split("=", 1)
        key = key.strip()
        value = value.strip()
        if len(value) >= 2 and value[0] == value[-1] and value[0] in {'"', "'"}:
            value = value[1:-1]
        if key:
            os.environ.setdefault(key, value)


def load_dotenv() -> None:
    """Fill unset variables from a local .env. Existing environment wins."""
    roots = [Path.cwd(), Path(__file__).resolve().parents[1]]
    seen: set[Path] = set()
    for root in roots:
        path = (root / ".env").resolve()
        if path in seen or not path.is_file():
            continue
        seen.add(path)
        _apply_env_file(path)


def _mode(raw: str) -> str:
    value = raw.strip().lower()
    if value in {"live", "model", "1", "true", "yes"}:
        return "live"
    return "mock"


def _int(name: str, default: int) -> int:
    raw = os.environ.get(name, "").strip()
    if not raw:
        return default
    try:
        return int(raw)
    except ValueError as exc:
        raise SystemExit(f"{name} must be an integer.") from exc


def _float(name: str, default: float) -> float:
    raw = os.environ.get(name, "").strip()
    if not raw:
        return default
    try:
        return float(raw)
    except ValueError as exc:
        raise SystemExit(f"{name} must be a number.") from exc


@dataclass(frozen=True)
class Settings:
    llm_mode: str
    llm_base_url: str
    llm_model: str
    llm_api_key: str
    llm_timeout: float
    host: str
    port: int
    user_agent: str = USER_AGENT

    @classmethod
    def from_env(cls) -> Settings:
        load_dotenv()
        return cls(
            llm_mode=_mode(os.environ.get("WALK_CUE_LLM_MODE", "mock")),
            llm_base_url=os.environ.get(
                "WALK_CUE_LLM_BASE_URL", "http://127.0.0.1:11434/v1"
            ).strip(),
            llm_model=os.environ.get("WALK_CUE_LLM_MODEL", "gemma3").strip() or "gemma3",
            llm_api_key=os.environ.get("WALK_CUE_LLM_API_KEY", "").strip(),
            llm_timeout=_float("WALK_CUE_LLM_TIMEOUT", 20.0),
            host=os.environ.get("WALK_CUE_HOST", "127.0.0.1").strip() or "127.0.0.1",
            port=_int("WALK_CUE_PORT", 8000),
        )

    @property
    def live(self) -> bool:
        return self.llm_mode == "live"
