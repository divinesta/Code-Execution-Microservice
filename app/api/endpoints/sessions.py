from fastapi import APIRouter, HTTPException, status
from pydantic import BaseModel
from typing import Optional

from app.services.execution import execution_service

router = APIRouter()


class SessionCreate(BaseModel):
    language: str


class SessionResponse(BaseModel):
    session_id: str
    language: str
    websocket_url: str


@router.post("/", response_model=SessionResponse)
async def create_session(session_data: SessionCreate):
    """Create a new code execution session"""
    try:
        # Create a new session
        session_id = await execution_service.create_session(session_data.language)

        # Return session details
        return {
            "session_id": session_id,
            "language": session_data.language,
            "websocket_url": f"/ws/terminal/{session_id}"
        }
    except ValueError as e:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=str(e)
        )
    except Exception as e:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Failed to create session: {str(e)}"
        )


@router.delete("/{session_id}")
async def terminate_session(session_id: str):
    """Terminate a session and clean up resources"""
    success = await execution_service.terminate_session(session_id)

    if success:
        return {"message": f"Session {session_id} terminated successfully"}
    else:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Session {session_id} not found or termination failed"
        )
