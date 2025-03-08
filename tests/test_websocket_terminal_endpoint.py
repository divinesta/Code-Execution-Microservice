import pytest
import json
from unittest.mock import patch, AsyncMock, MagicMock
from fastapi.testclient import TestClient
from fastapi.websockets import WebSocket
from app.main import app

client = TestClient(app)


@pytest.fixture
def mock_execution_service():
    with patch("app.services.execution.execution_service") as mock_service:
        # Mock the execute_code_with_streaming method
        async def execute_streaming_mock(session_id, code, input_data, timeout, callback):
            # Call the callback with a sample result
            await callback({
                'output': 'Hello, World!',
                'error': None,
                'exit_code': 0,
                'complete': True
            })
            # Return a result similar to execute_code
            return {
                'exit_code': 0,
                'output': 'Hello, World!',
                'error': None
            }

        mock_service.execute_code_with_streaming = AsyncMock(
            side_effect=execute_streaming_mock)
        mock_service.terminate_session = AsyncMock(return_value=True)
        yield mock_service


class TestWebSocketConnection:
    @pytest.mark.asyncio
    async def test_websocket_connection(self, mock_execution_service):
        with client.websocket_connect("/ws/terminal/test-session-id") as websocket:
            # First message should be connection established
            data = websocket.receive_json()
            assert data["type"] == "connection.established"
            assert data["session_id"] == "test-session-id"

            # Send code execution message
            websocket.send_json({
                "code": "print('Hello, World!')"
            })

            # Expect streamed output
            response = websocket.receive_json()
            assert response["type"] == "terminal.code_chunk"
            assert response["output"] == "Hello, World!"
            assert response["complete"] is True
            assert response["exit_code"] == 0
            assert response["error"] is None

            # Test ping/pong
            websocket.send_json({
                "ping": True,
                "timestamp": 123456789
            })

            pong = websocket.receive_json()
            assert pong["type"] == "pong"
            assert pong["timestamp"] == 123456789

    @pytest.mark.asyncio
    async def test_websocket_code_execution_error(self, mock_execution_service):
        # Update mock to return an error
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

        mock_execution_service.execute_code_with_streaming.side_effect = execute_error_mock

        with client.websocket_connect("/ws/terminal/test-session-id") as websocket:
            # Skip connection established message
            websocket.receive_json()

            # Send code with syntax error
            websocket.send_json({
                "code": "print('Syntax error"  # Missing closing quote
            })

            # Expect error response
            response = websocket.receive_json()
            assert response["type"] == "terminal.code_chunk"
            assert response["error"] == "SyntaxError: invalid syntax"
            assert response["exit_code"] == 1
