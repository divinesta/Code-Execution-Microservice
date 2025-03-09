import os
from pydantic_settings import BaseSettings
from dotenv import load_dotenv

# Load environment variables from .env file
load_dotenv()

# Define settings class


class Settings(BaseSettings):
    API_V1_STR: str = "/api"
    PROJECT_NAME: str = "Code Execution Service"
    ENVIRONMENT: str = os.getenv("ENVIRONMENT", "development")
    DEBUG: bool = ENVIRONMENT == "development"

    # Docker configuration
    USE_DOCKER: bool = os.getenv("USE_DOCKER", "true").lower() == "true"
    WORKSPACE_ROOT: str = os.getenv("WORKSPACE_ROOT", "/workspace")
    MAX_EXECUTION_TIME: int = int(os.getenv("MAX_EXECUTION_TIME", "10"))

    # Security
    API_KEY: str = os.getenv("API_KEY", "")

    # Other security settings
    ALLOWED_HOSTS: list = ["*"]
    # Add frontend URL if applicable
    CORS_ORIGINS: list = ["http://localhost:3000", "http://localhost:5173"] if DEBUG else ["*"]

    # Language configurations
    LANGUAGE_IMAGES: dict[str, str] = {
        "python": "python:3.9-slim",
        "c": "gcc:latest",
        "cpp": "gcc:latest",
        "java": "openjdk:11",
    }

    FILE_EXTENSIONS: dict[str, str] = {
        "python": "py",
        "c": "c",
        "cpp": "cpp",
        "java": "java",
    }


# Create settings instance
settings = Settings()
