import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from unittest.mock import patch

from app.main import app
from app.core.security import get_api_key

API_KEY = "api_key"


@pytest.fixture
def client():
    app.dependency_overrides[get_api_key] = lambda: API_KEY
    client_instance = TestClient(app)
    yield client_instance
    app.dependency_overrides.pop(get_api_key, None)
