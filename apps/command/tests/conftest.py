import os

os.environ["DATABASE_URL"] = "sqlite:////tmp/survey-command-pytest.db"
os.environ["COMMAND_SECRET_KEY"] = "test-secret-key"
os.environ["COMMAND_ADMIN_EMAIL"] = "owner@survey.test"
os.environ["COMMAND_ADMIN_PASSWORD"] = "correct-horse"
os.environ["COMMAND_API_KEY"] = "test-api-key"
os.environ["RESTO_API_KEY"] = "resto-test-key"
os.environ["MAUTIC_INTERNAL_URL"] = "http://127.0.0.1:9"
os.environ["POSTIZ_INTERNAL_URL"] = "http://127.0.0.1:9"
os.environ["N8N_INTERNAL_URL"] = "http://127.0.0.1:9"
os.environ["DATA_DIR"] = "/tmp/survey-command-data"
os.environ["OLLAMA_BASE_URL"] = ""
os.environ["OLLAMA_TEXT_MODEL"] = ""
os.environ["OLLAMA_VISION_MODEL"] = ""
os.environ["COMMAND_PROBE_TIMEOUT"] = "0.4"

import pytest
from fastapi.testclient import TestClient


@pytest.fixture(autouse=True)
def reset_db():
    from app.db import Base, SessionLocal, engine
    from app.domain import ensure_profiles

    Base.metadata.drop_all(bind=engine)
    Base.metadata.create_all(bind=engine)
    db = SessionLocal()
    try:
        ensure_profiles(db)
    finally:
        db.close()
    yield


@pytest.fixture
def client():
    from app.main import app

    with TestClient(app) as test_client:
        yield test_client


@pytest.fixture
def owner(client):
    response = client.post("/api/login", json={"email": "owner@survey.test", "password": "correct-horse"})
    assert response.status_code == 200, response.text
    return client
