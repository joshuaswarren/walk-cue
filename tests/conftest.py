import pytest

from walkcue.config import Settings


@pytest.fixture
def settings() -> Settings:
    return Settings(
        llm_mode="mock",
        llm_base_url="http://127.0.0.1:11434/v1",
        llm_model="gemma3",
        llm_api_key="",
        llm_timeout=5.0,
        host="127.0.0.1",
        port=8000,
    )
