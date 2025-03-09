FROM python:3.9.20-alpine3.20

# Install system dependencies with apk
RUN apk update && apk add docker-cli docker-openrc containerd && rm -rf /var/cache/apk/*

# Set working directory
WORKDIR /app

# Copy requirements first to leverage Docker cache
COPY requirements.txt .
# Install requirements but skip Windows-specific packages
RUN pip install -r requirements.txt

# Copy application code
COPY . .

# Create workspace directory
RUN mkdir -p /tmp/user_workspaces

# Expose port
EXPOSE 8000

# Start the FastAPI application with Uvicorn
CMD ["uvicorn", "app.main:app", "--host", "", "--port", "8000"]