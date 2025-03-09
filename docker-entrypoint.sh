#!/bin/sh
set -e

# Get Docker GID from the socket file
DOCKER_GID=$(stat -c '%g' /var/run/docker.sock)

# Create docker group with the same GID as the host
addgroup -g $DOCKER_GID docker || true
adduser myuser docker || true

# Switch to myuser and execute the CMD
exec su-exec myuser "$@"
