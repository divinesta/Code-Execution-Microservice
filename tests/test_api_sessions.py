import pytest
from unittest.mock import patch, AsyncMock
from fastapi.testclient import TestClient
from app.main import app

client = TestClient(app)
API_KEY = "development_api_key"
API_PREFIX = "/api"


@pytest.fixture
def mock_execution_service():
    with patch("app.services.execution.execution_service") as mock_service:
        mock_service.create_session = AsyncMock(return_value="test-session-id")
        mock_service.terminate_session = AsyncMock(return_value=True)
        yield mock_service


def test_create_session(mock_execution_service):
    # Prepare test data
    payload = {
        "language": "python",
        "initial_code": "print('Hello, World!')"
    }

    # Execute test
    response = client.post(
        f"{API_PREFIX}/sessions/",
        json=payload,
        headers={"X-API-Key": API_KEY}
    )

    # Verify response
    assert response.status_code == 200
    data = response.json()
    assert data["session_id"] == "test-session-id"
    assert data["language"] == "python"
    assert data["websocket_url"] == "/ws/terminal/test-session-id"

    # Verify mock was called
    mock_execution_service.create_session.assert_awaited_once_with("python")


def test_create_session_invalid_api_key():
    # Prepare test data
    payload = {"language": "python"}

    # Execute test with invalid API key
    response = client.post(
        f"{API_PREFIX}/sessions/",
        json=payload,
        headers={"X-API-Key": "invalid-key"}
    )

    # Verify unauthorized response
    assert response.status_code == 401
    assert "Invalid API Key" in response.json()["detail"]


def test_terminate_session(mock_execution_service):
    # Execute test
    response = client.delete(
        f"{API_PREFIX}/sessions/test-session-id",
        headers={"X-API-Key": API_KEY}
    )

    # Verify response
    assert response.status_code == 200
    assert response.json()[
        "message"] == "Session test-session-id terminated successfully"

    # Verify mock was called
    mock_execution_service.terminate_session.assert_awaited_once_with(
        "test-session-id")


def test_terminate_nonexistent_session(mock_execution_service):
    # Configure mock to return False (session not found)
    mock_execution_service.terminate_session.return_value = False

    # Execute test
    response = client.delete(
        f"{API_PREFIX}/sessions/nonexistent-id",
        headers={"X-API-Key": API_KEY}
    )

    # Verify response
    assert response.status_code == 404
    assert "not found" in response.json()["detail"]
