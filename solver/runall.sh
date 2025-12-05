#!/bin/bash
# -------------------------
# Bash script to start backend, Redis, Docker executor, and frontend for macOS
# -------------------------

# Exit immediately if a command exits with a non-zero status.
set -e

# --- Paths ---
backendPath="./backend"

# --- Step 1: Build and run math-executor Docker image ---
echo "Building Docker image for math-executor..."
docker build -t math-executor "$backendPath"

echo "Running math-executor container on port 8000..."
# Stop and remove existing container if it's running
docker stop math-executor 2>/dev/null || true
docker rm math-executor 2>/dev/null || true

# Run the new container
docker run -d --name math-executor -p 8000:8000 math-executor

# --- Step 2: Run Redis ---
echo "Checking for existing Redis container..."
# Check if Redis container exists (uses a specific filter to check for the container name)
redisContainer=$(docker ps -a --filter "name=^my-redis$" --format "{{.Names}}")

if [ "$redisContainer" = "my-redis" ]; then
    echo "Redis container already exists. Starting it..."
    docker start my-redis
else
    echo "Running Redis container on port 6379..."
    docker run -d --name my-redis -p 6379:6379 redis
fi

# --- Step 3: Start FastAPI backend ---
echo "Starting FastAPI backend on port 5001 in a new terminal window..."
# Use 'open' to launch a new terminal and execute the commands
# The & at the end detaches the process from the script, letting the script continue.
osascript -e 'tell application "Terminal" to do script "cd '$PWD'/'$backendPath' && python -m uvicorn app:app --reload --port 5001"'

# --- Step 4: Start frontend ---
echo "Starting frontend dev server in a new terminal window..."
# Use 'open' to launch a new terminal and execute the commands
# Assumes the 'npm run dev' command should be run from the root directory ($PWD).
osascript -e 'tell application "Terminal" to do script "cd '$PWD' && npm run dev"'

echo "Setup complete. Backend (5001), Executor (8000), and Redis (6379) are running in Docker."