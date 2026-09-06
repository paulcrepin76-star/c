import os
import tempfile
from pathlib import Path

_TMP = Path(tempfile.mkdtemp(prefix="grok-bot-tests-"))
(_TMP / "repo").mkdir(parents=True, exist_ok=True)
(_TMP / "data").mkdir(parents=True, exist_ok=True)

os.environ.setdefault("RESTO_API_KEY", "test-key")
os.environ.setdefault("RESTO_URL", "http://resto-core:8080")
os.environ.setdefault("PUBLIC_URL", "http://100.116.48.120:8088")
os.environ["REPO_DIR"] = str(_TMP / "repo")
os.environ["APPDATA_DIR"] = str(_TMP / "repo")
os.environ["DATA_DIR"] = str(_TMP / "data")
os.environ["XAI_API_KEY"] = ""
os.environ["TELEGRAM_BOT_TOKEN"] = ""
os.environ["TELEGRAM_ALLOWED_CHAT_IDS"] = ""

import httpx
import pytest

from app import state
from app.settings import settings

COMPOSE_YML = """name: resto
services:
  resto-core:
    image: resto-core:local
    ports:
      - "8088:8080"
networks:
  resto:
    name: resto
"""


@pytest.fixture(autouse=True)
def clean_state():
    state.reset()
    repo = Path(settings.repo_dir)
    (repo / "compose.yml").write_text(COMPOSE_YML, encoding="utf-8")
    extra = repo / "compose.extra.yml"
    if extra.exists():
        extra.unlink()
    actions = Path(settings.data_dir) / "actions.log"
    if actions.exists():
        actions.unlink()
    settings.xai_api_key = ""
    settings.require_confirm = True
    settings.allow_custom_images = True
    settings.telegram_allowed_chat_ids = ""
    yield


@pytest.fixture
def mock_http(monkeypatch):
    """Point a module's httpx.Client at a handler instead of the network."""
    real_client = httpx.Client

    def install(module, handler):
        def factory(*_args, **_kwargs):
            return real_client(transport=httpx.MockTransport(handler))

        monkeypatch.setattr(module.httpx, "Client", factory)

    return install
