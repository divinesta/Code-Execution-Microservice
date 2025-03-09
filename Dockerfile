FROM python:3.9.20-alpine3.20

# Install system dependencies with apk
RUN apk update && apk add docker-cli docker-openrc containerd && rm -rf /var/cache/apk/*

RUN mkdir -p /workspace

WORKDIR /app

# Copy requirements first to leverage Docker cache
COPY requirements.txt .
# Install requirements
RUN pip install -r requirements.txt

# Copy application code
COPY . .


# Expose port
EXPOSE 8000

# Start the FastAPI application with Uvicorn
CMD ["uvicorn", "app.main:app", "--host", "", "--port", "8000"]