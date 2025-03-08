import os
from pydantic_settings import BaseSettings
from dotenv import load_dotenv

# Load environment variables from .env file
load_dotenv()

# Define settings class
class Settings(BaseSettings):
    API_V1_STR: str = "/api"
    PROJECT_NAME: str = "Code Execution Service"

    # Docker configuration
    USE_DOCKER: bool = os.getenv("USE_DOCKER", "true").lower() == "true"
    WORKSPACE_ROOT: str = os.getenv("WORKSPACE_ROOT", "/tmp/user_workspaces")
    MAX_EXECUTION_TIME: int = int(os.getenv("MAX_EXECUTION_TIME", "10"))

    # Security
    API_KEY: str = os.getenv("API_KEY", "")
    ALLOWED_ORIGINS: list = os.getenv("ALLOWED_ORIGINS", "").split(",")

    # Language configurations
    LANGUAGE_IMAGES = {
        "python": "python:3.9-slim",
        "cpp": "gcc:latest",
        "java": "openjdk:11",
        "javascript": "node:16"
    }

    FILE_EXTENSIONS = {
        "python": "py",
        "cpp": "cpp",
        "java": "java",
        "javascript": "js"
    }

# Create settings instance
settings = Settings()
