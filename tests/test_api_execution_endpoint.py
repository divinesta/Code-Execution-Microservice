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
        mock_service.execute_code = AsyncMock(return_value={
            "exit_code": 0,
            "output": "Hello, World!",
            "error": None
        })
        yield mock_service


def test_execute_code(mock_execution_service):
    # Prepare test data
    payload = {
        "session_id": "test-session-id",
        "code": "print('Hello, World!')",
        "input_data": "",
        "timeout": 5
    }

    # Execute test
    response = client.post(
        f"{API_PREFIX}/execute/",
        json=payload,
        headers={"X-API-Key": API_KEY}
    )

    # Verify response
    assert response.status_code == 200
    data = response.json()
    assert data["exit_code"] == 0
    assert data["output"] == "Hello, World!"
    assert data["error"] is None

    # Verify mock was called correctly
    mock_execution_service.execute_code.assert_awaited_once_with(
        "test-session-id",
        "print('Hello, World!')",
        "",
        5
    )


def test_execute_code_session_not_found(mock_execution_service):
    # Configure mock to raise ValueError (session not found)
    mock_execution_service.execute_code.side_effect = ValueError(
        "Session not found")

    # Prepare test data
    payload = {
        "session_id": "nonexistent-id",
        "code": "print('Hello')"
    }

    # Execute test
    response = client.post(
        f"{API_PREFIX}/execute/",
        json=payload,
        headers={"X-API-Key": API_KEY}
    )

    # Verify response
    assert response.status_code == 400
    assert "Session not found" in response.json()["detail"]


def test_execute_code_runtime_error(mock_execution_service):
    # Configure mock to return error output
    mock_execution_service.execute_code.return_value = {
        "exit_code": 1,
        "output": "",
        "error": "NameError: name 'undefined_variable' is not defined"
    }

    # Prepare test data
    payload = {
        "session_id": "test-session-id",
        "code": "print(undefined_variable)"
    }

    # Execute test
    response = client.post(
        f"{API_PREFIX}/execute/",
        json=payload,
        headers={"X-API-Key": API_KEY}
    )

    # Verify response
    assert response.status_code == 200  # Still 200 since the API executed correctly
    data = response.json()
    assert data["exit_code"] == 1
    assert data["error"] == "NameError: name 'undefined_variable' is not defined"
