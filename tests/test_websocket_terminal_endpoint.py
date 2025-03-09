import pytest
import json
from unittest.mock import patch, AsyncMock, MagicMock
from fastapi.testclient import TestClient
from app.main import app

API_KEY = "api_key"


@pytest.fixture
def client():
    from app.core.security import get_api_key
    app.dependency_overrides[get_api_key] = lambda: API_KEY
    client_instance = TestClient(app)
    yield client_instance
    app.dependency_overrides.pop(get_api_key, None)


@pytest.fixture
def mock_execution_service():
    from app.services.execution import execution_service
    with patch.object(execution_service, 'execute_code_with_streaming', new=AsyncMock()) as mock_method:
        async def execute_streaming_mock(session_id, code, input_data, timeout, callback):
            await callback({
                'output': 'Hello, World!',
                'error': None,
                'exit_code': 0,
                'complete': True
            })
            return {
                'exit_code': 0,
                'output': 'Hello, World!',
                'error': None
            }
        mock_method.side_effect = execute_streaming_mock
        with patch.object(execution_service, 'terminate_session', new=AsyncMock(return_value=True)):
            # Make sure the session exists in active_containers to prevent session-not-found errors
            execution_service.active_containers = {
                "test-session-id": {"container": MagicMock(), "language": "python"}}
            yield mock_method


class TestWebSocketConnection:
    @pytest.mark.asyncio
    async def test_websocket_connection(self, client, mock_execution_service):
        from app.services.execution import execution_service
        execution_service.active_containers = {
            "test-session-id": {"container": MagicMock(), "language": "python"}}

        # Create a session through the API first
        response = client.post(
            "/api/sessions/",
            json={"language": "python"},
            headers={"X-API-Key": API_KEY}
        )

        # Connect via WebSocket
        with client.websocket_connect("/ws/terminal/test-session-id") as websocket:
            data = websocket.receive_json()
            assert data["type"] == "connection.established"
            assert data["session_id"] == "test-session-id"
            # Send a code execution message
            websocket.send_json({"code": "print('Hello, World!')"})
            response_data = websocket.receive_json()
            assert response_data["type"] == "terminal.code_chunk"
            assert response_data["output"] == "Hello, World!"
            assert response_data["complete"] is True
            assert response_data["exit_code"] == 0
            assert response_data["error"] is None
            # Test ping/pong messaging
            websocket.send_json({
                "ping": True,
                "timestamp": 123456789
            })
            pong = websocket.receive_json()
            assert pong["type"] == "pong"
            assert pong["timestamp"] == 123456789

    @pytest.mark.asyncio
    async def test_websocket_code_execution_error(self, client, mock_execution_service):
        from app.services.execution import execution_service
        execution_service.active_containers = {
            "test-session-id": {"container": MagicMock(), "language": "python"}}

        async def execute_error_mock(session_id, code, input_data, timeout, callback):
            await callback({
                'output': '',
                'error': 'SyntaxError: invalid syntax',
                'exit_code': 1,
                'complete': True
            })
            return {
                'exit_code': 1,
                'output': '',
                'error': 'SyntaxError: invalid syntax'
            }
        mock_execution_service.side_effect = execute_error_mock

        with client.websocket_connect("/ws/terminal/test-session-id") as websocket:
            # Receive the connection established message
            websocket.receive_json()
            # Send code with a syntax error (simulate missing closing quote)
            websocket.send_json({"code": "print('Syntax error"})
            response_data = websocket.receive_json()
            # We now accept either a code_chunk containing error info or a terminal.error message.
            assert response_data["type"] in [
                "terminal.code_chunk", "terminal.error"]
