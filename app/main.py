from fastapi import FastAPI, Depends
from fastapi.middleware.cors import CORSMiddleware
import logging
import os

from app.core.config import settings
from app.core.security import get_api_key
from app.api.endpoints import sessions, execution
from app.api.websockets import terminal

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    handlers=[logging.StreamHandler()]
)

logger = logging.getLogger(__name__)


# Create application
app = FastAPI(
    title=settings.PROJECT_NAME,
    version="1.0.0",
    debug=settings.DEBUG,
    docs_url="/docs" if settings.DEBUG else None,
    redoc_url="/redoc" if settings.DEBUG else None,
    openapi_url=f"{settings.API_V1_STR}/openapi.json" if settings.DEBUG else None
)

# Configure CORS
app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.CORS_ORIGINS,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Create workspace directory if it doesn't exist
os.makedirs(settings.WORKSPACE_ROOT, exist_ok=True)

# Include API routers
app.include_router(
    sessions.router,
    prefix=f"{settings.API_V1_STR}/sessions",
    dependencies=[Depends(get_api_key)],
    tags=["sessions"]
)
# Include WebSocket endpoint
app.include_router(terminal.router, tags=["terminal"])

app.include_router(
    execution.router,
    prefix=f"{settings.API_V1_STR}/execute",
    dependencies=[Depends(get_api_key)],
    tags=["execution"]
)

# Root endpoint for health check
@app.get("/", tags=["Health"])
def read_root():
    return {"message": f"{settings.PROJECT_NAME} is running"}
