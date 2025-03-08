from fastapi import Security, HTTPException, status
from fastapi.security import APIKeyHeader
from .config import settings

# Define API key header with auto_error=False to handle missing headers in our custom function
api_key_header = APIKeyHeader(name="X-API-Key", auto_error=False)


async def get_api_key(api_key: str = Security(api_key_header)):
    # Validate the provided API key against our configured key
    if api_key != settings.API_KEY:
        # If keys don't match, raise 401 Unauthorized exception
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid API Key"
        )
    # Return the valid API key
    return api_key
