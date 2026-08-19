"""Fixtures compartilhadas dos testes.

As variaveis de ambiente sao definidas *antes* de qualquer import da aplicacao porque
`Settings` valida a config no momento do import -- sem elas o proprio import falharia.
Isso e efeito colateral desejado do fail-fast em `app/core/config.py`.
"""

import os

os.environ.setdefault("POSTGRES_USER", "test")
os.environ.setdefault("POSTGRES_PASSWORD", "test")
os.environ.setdefault("POSTGRES_DB", "test")
os.environ.setdefault("POSTGRES_HOST", "localhost")
os.environ.setdefault("REDIS_HOST", "localhost")
os.environ.setdefault("JWT_SECRET", "test-secret")
os.environ.setdefault("APP_DEBUG", "false")

import pytest  # noqa: E402
from fastapi.testclient import TestClient  # noqa: E402

from main import app  # noqa: E402


@pytest.fixture
def client() -> TestClient:
    return TestClient(app)
