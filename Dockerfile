FROM python:3.9.20-alpine3.20

# Install system dependencies with apk
RUN apk update && apk add docker-cli docker-openrc containerd && rm -rf /var/cache/apk/*

# Create a non-root user and workspace directory
RUN adduser --disabled-password --gecos '' myuser && \
   mkdir -p /home/myuser/workspace

# Switch to root to add the docker group and add myuser to it
USER root
RUN addgroup docker && adduser myuser docker

# Switch back to myuser
USER myuser

# Ensure the local bin directory is in PATH
ENV PATH="/home/myuser/.local/bin:$PATH"

# Set working directory
WORKDIR /app

# Copy requirements first to leverage Docker cache
COPY requirements.txt .
# Install requirements
RUN pip install -r requirements.txt

# Copy application code
COPY . .

# Expose port
EXPOSE 8000

ENTRYPOINT ["docker-entrypoint.sh"]

# Start the FastAPI application with Uvicorn
CMD ["uvicorn", "app.main:app", "--host", "", "--port", "8000"]