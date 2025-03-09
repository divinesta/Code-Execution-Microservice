import pytest
from unittest.mock import patch, AsyncMock
from fastapi.testclient import TestClient
from app.main import app

API_KEY = "api_key"
API_PREFIX = "/api"

# Patch the execution_service where it is used (in sessions.py)


@pytest.fixture
def mock_execution_service():
    from app.api.endpoints import sessions
    with patch.object(sessions.execution_service, 'create_session', new=AsyncMock(return_value="test-session-id")) as cs_mock:
        with patch.object(sessions.execution_service, 'terminate_session', new=AsyncMock(return_value=True)) as ts_mock:
            yield cs_mock


def test_create_session(client, mock_execution_service):
    payload = {
        "language": "python",
        "initial_code": "print('Hello, World!')"
    }
    response = client.post(
        f"{API_PREFIX}/sessions/",
        json=payload,
        headers={"X-API-Key": API_KEY}
    )
    assert response.status_code == 200
    data = response.json()
    assert data["session_id"] == "test-session-id"
    assert data["language"] == "python"
    assert data["websocket_url"] == "/ws/terminal/test-session-id"
    from app.api.endpoints import sessions
    # Verify that create_session was awaited once with "python"
    sessions.execution_service.create_session.assert_awaited_once_with(
        "python")


def test_create_session_invalid_api_key(client):
    from app.core.security import get_api_key
    # Remove the dependency override so that the real API key validation runs.
    if get_api_key in app.dependency_overrides:
        app.dependency_overrides.pop(get_api_key)
    payload = {"language": "python"}
    response = client.post(
        f"{API_PREFIX}/sessions/",
        json=payload,
        headers={"X-API-Key": "invalid-key"}
    )
    assert response.status_code == 401
    assert "Invalid API Key" in response.json()["detail"]


def test_terminate_session(client, mock_execution_service):
    from app.api.endpoints import sessions
    response = client.delete(
        f"{API_PREFIX}/sessions/test-session-id",
        headers={"X-API-Key": API_KEY}
    )
    assert response.status_code == 200
    assert response.json()[
        "message"] == "Session test-session-id terminated successfully"
    sessions.execution_service.terminate_session.assert_awaited_once_with(
        "test-session-id")


def test_terminate_nonexistent_session(client):
    from app.api.endpoints import sessions
    # Override termination to simulate a session not found.
    sessions.execution_service.terminate_session = AsyncMock(
        return_value=False)
    response = client.delete(
        f"{API_PREFIX}/sessions/nonexistent-id",
        headers={"X-API-Key": API_KEY}
    )
    assert response.status_code == 404
    assert "not found" in response.json()["detail"]
