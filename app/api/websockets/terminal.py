from fastapi import APIRouter, WebSocket, WebSocketDisconnect
import json
import logging
from typing import Dict, List
import asyncio

from app.services.execution import execution_service
from app.core.config import settings

router = APIRouter()
logger = logging.getLogger(__name__)

# Store active WebSocket connections
active_connections: Dict[str, List[WebSocket]] = {}


@router.websocket("/ws/terminal/{session_id}")
async def terminal_websocket(websocket: WebSocket, session_id: str):
    """WebSocket endpoint for terminal sessions"""
    # Accept the WebSocket connection
    await websocket.accept()

    # Check if the session exists
    try:
        # Add connection to active connections for this session
        if session_id not in active_connections:
            active_connections[session_id] = []
        active_connections[session_id].append(websocket)

        # Send connection confirmation
        await websocket.send_json({
            'type': 'connection.established',
            'session_id': session_id
        })

        # Handle WebSocket communication
        try:
            while True:
                # Receive message from WebSocket
                data = await websocket.receive_text()
                data = json.loads(data)

                # Handle different message types
                if 'code' in data:
                    # Execute submitted code
                    code = data['code']
                    input_data = data.get('input_data')
                    timeout = data.get('timeout', settings.MAX_EXECUTION_TIME)

                    try:
                        # Define callback for streaming output
                        async def stream_callback(chunk_data):
                            await websocket.send_json({
                                'type': 'terminal.code_chunk',
                                'output': chunk_data.get('output', ''),
                                'complete': chunk_data.get('complete', False),
                                'exit_code': chunk_data.get('exit_code'),
                                'error': chunk_data.get('error'),
                                'waiting_for_input': chunk_data.get('waiting_for_input', False)
                            })

                            # If there are multiple connections for this session,
                            # broadcast to others
                            if len(active_connections[session_id]) > 1:
                                for conn in active_connections[session_id]:
                                    if conn != websocket:
                                        await conn.send_json({
                                            'type': 'terminal.code_broadcast',
                                            'output': chunk_data.get('output', ''),
                                            'complete': chunk_data.get('complete', False),
                                            'waiting_for_input': chunk_data.get('waiting_for_input', False)
                                        })

                        # Execute with streaming
                        await execution_service.execute_code_with_streaming(
                            session_id,
                            code,
                            input_data,
                            timeout,
                            callback=stream_callback
                        )

                    except Exception as e:
                        logger.error(f"Error executing code: {str(e)}")
                        await websocket.send_json({
                            'type': 'terminal.error',
                            'error': str(e)
                        })

                elif 'command' in data:
                    # Execute shell command (limited functionality)
                    # This would need additional security measures in production
                    command = data['command']
                    # Implementation would depend on your security requirements
                    await websocket.send_json({
                        'type': 'terminal.command_response',
                        'output': f"Command execution not implemented: {command}",
                        'exit_code': 1
                    })

                elif 'ping' in data:
                    # Simple ping/pong to keep connection alive
                    await websocket.send_json({
                        'type': 'pong',
                        'timestamp': data.get('timestamp')
                    })

                elif 'input_response' in data:
                    # Process user's input response to a previous prompt
                    input_response = data['input_response']

                    # Store this in the active session or container
                    if session_id in execution_service.active_containers:
                        container_info = execution_service.active_containers[session_id]
                        if 'input_queue' not in container_info:
                            container_info['input_queue'] = asyncio.Queue()

                        await container_info['input_queue'].put(input_response)
                        await websocket.send_json({
                            'type': 'terminal.input_processed',
                            'status': 'success'
                        })
                    elif session_id in execution_service.active_sessions:
                        if 'input_queue' not in execution_service.active_sessions[session_id]:
                            execution_service.active_sessions[session_id]['input_queue'] = asyncio.Queue(
                            )

                        await execution_service.active_sessions[session_id]['input_queue'].put(input_response)
                        await websocket.send_json({
                            'type': 'terminal.input_processed',
                            'status': 'success'
                        })
                    else:
                        await websocket.send_json({
                            'type': 'terminal.error',
                            'error': 'No active execution waiting for input'
                        })

                else:
                    # Unknown message type
                    await websocket.send_json({
                        'type': 'terminal.error',
                        'error': 'Unknown message type'
                    })

        except WebSocketDisconnect:
            logger.info(f"WebSocket disconnected for session {session_id}")

        except Exception as e:
            logger.error(f"WebSocket error: {str(e)}")
            await websocket.send_json({
                'type': 'terminal.error',
                'error': f"WebSocket error: {str(e)}"
            })

    finally:
        # Clean up when disconnected
        if session_id in active_connections:
            if websocket in active_connections[session_id]:
                active_connections[session_id].remove(websocket)

            # If this was the last connection, terminate the session
            if len(active_connections[session_id]) == 0:
                await execution_service.terminate_session(session_id)
                del active_connections[session_id]
