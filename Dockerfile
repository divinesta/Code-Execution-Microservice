FROM python:3.9-slim

# Install system dependencies (e.g., docker CLI)
RUN apt-get update && apt-get install -y docker.io && rm -rf /var/lib/apt/lists/*

# Create a non-root user and a dedicated workspace directory
RUN adduser --disabled-password --gecos '' myuser && \
   mkdir -p /home/myuser/workspace

# Switch to non-root user
USER myuser

WORKDIR /app

# Copy application code
COPY . /app

# Install Python dependencies
RUN pip install --no-cache-dir -r requirements.txt

EXPOSE 8000

# Start the FastAPI application with Uvicorn
CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000"]