import pytest
from unittest.mock import AsyncMock
from app.main import app

API_KEY = "api_key"
API_PREFIX = "/api"


@pytest.fixture
def mock_execution_service():
    from app.services.execution import execution_service
    # Patch the execute_code method and ensure the session exists in active_containers.
    with pytest.MonkeyPatch().context() as mp:
        mp.setattr(execution_service, 'execute_code', AsyncMock(return_value={
            "exit_code": 0,
            "output": "Hello, World!",
            "error": None
        }))
        execution_service.active_containers = {
            "test-session-id": {"container": object(), "language": "python"}
        }
        yield execution_service


def test_execute_code(client, mock_execution_service):
    payload = {
        "session_id": "test-session-id",
        "code": "print('Hello, World!')",
        "input_data": "",
        "timeout": 5
    }
    response = client.post(
        f"{API_PREFIX}/execute/",
        json=payload,
        headers={"X-API-Key": API_KEY}
    )
    assert response.status_code == 200
    data = response.json()
    assert data["exit_code"] == 0
    assert data["output"] == "Hello, World!"
    assert data["error"] is None


def test_execute_code_session_not_found(client, mock_execution_service):
    # Simulate a session not found by making sure it does not exist in the dict.
    from app.services.execution import execution_service
    if "nonexistent-id" in execution_service.active_containers:
        execution_service.active_containers.pop("nonexistent-id")
    mock_execution_service.execute_code.side_effect = ValueError(
        "Session not found")
    payload = {
        "session_id": "nonexistent-id",
        "code": "print('Hello')"
    }
    response = client.post(
        f"{API_PREFIX}/execute/",
        json=payload,
        headers={"X-API-Key": API_KEY}
    )
    # In this case the endpoint returns a 400 due to ValueError
    assert response.status_code == 400
    assert "Session not found" in response.json()["detail"]


def test_execute_code_runtime_error(client, mock_execution_service):
    mock_execution_service.execute_code.return_value = {
        "exit_code": 1,
        "output": "",
        "error": "NameError: name 'undefined_variable' is not defined"
    }
    payload = {
        "session_id": "test-session-id",
        "code": "print(undefined_variable)"
    }
    response = client.post(
        f"{API_PREFIX}/execute/",
        json=payload,
        headers={"X-API-Key": API_KEY}
    )
    assert response.status_code == 200
    data = response.json()
    assert data["exit_code"] == 1
    assert data["error"] == "NameError: name 'undefined_variable' is not defined"
