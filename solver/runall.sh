#!/bin/bash

# Stop any running containers
# (Using "docker compose" with a space)
docker compose down

# Build and start everything
# --build forces a rebuild of the images
docker compose up --build