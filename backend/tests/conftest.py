"""Pytest fixtures. Uses an isolated temp SQLite DB so tests never touch the dev database.

Environment is configured BEFORE importing any app module, because config is cached.
"""
import os
import tempfile

import pytest

# --- configure a throwaway test environment before app import ---
_TMP_DB = os.path.join(tempfile.gettempdir(), "dj_studio_test.db")
if os.path.exists(_TMP_DB):
    os.remove(_TMP_DB)
os.environ["DATABASE_URL"] = f"sqlite:///{_TMP_DB}"
os.environ["JWT_SECRET_KEY"] = "test-secret-key-not-for-production"
os.environ["AI_BACKEND"] = "local"

from fastapi.testclient import TestClient  # noqa: E402

from app.database import init_db  # noqa: E402
from app.main import app  # noqa: E402
from app.seed import seed  # noqa: E402


@pytest.fixture(scope="session", autouse=True)
def _db():
    init_db()
    seed()
    yield


@pytest.fixture
def client():
    return TestClient(app)


def _login(client, email, password):
    r = client.post("/api/v1/auth/login", json={"email": email, "password": password})
    assert r.status_code == 200, r.text
    return r.json()


@pytest.fixture
def admin_token(client):
    return _login(client, "admin@djstudio.dev", "admin123")["access_token"]


@pytest.fixture
def host_token(client):
    return _login(client, "host@djstudio.dev", "host1234")["access_token"]


@pytest.fixture
def listener_token(client):
    return _login(client, "dana@djstudio.dev", "listen12")["access_token"]


def auth(token):
    return {"Authorization": f"Bearer {token}"}
