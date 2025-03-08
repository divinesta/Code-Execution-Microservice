from fastapi import APIRouter, HTTPException, status
from pydantic import BaseModel
from typing import Optional

from app.services.execution import execution_service

router = APIRouter()


class CodeExecutionRequest(BaseModel):
    session_id: str
    code: str
    input_data: Optional[str] = None
    timeout: Optional[int] = None


class CodeExecutionResponse(BaseModel):
    exit_code: int
    output: str
    error: Optional[str] = None


@router.post("/", response_model=CodeExecutionResponse)
async def execute_code(request: CodeExecutionRequest):
    """Execute code in an existing session"""
    try:
        # Execute the code
        result = await execution_service.execute_code(
            request.session_id,
            request.code,
            request.input_data,
            request.timeout
        )

        return result
    except ValueError as e:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=str(e)
        )
    except Exception as e:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Execution failed: {str(e)}"
        )
