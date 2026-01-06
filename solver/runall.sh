#!/usr/bin/env bash
set -e

backendPath="./backend"

echo "Building Docker image for math-executor..."
# We keep the build step to ensure the container has the latest files
docker build -t math-executor "$backendPath"

echo "Restarting math-executor container..."
docker rm -f math-executor 2>/dev/null || true

# REMOVED: -v volume mount (Fixes permission/upload errors)
docker run -d \
  --name math-executor \
  -p 8000:8000 \
  math-executor

echo "Starting Redis..."
docker rm -f my-redis 2>/dev/null || true
docker run -d --name my-redis -p 6379:6379 redis

echo "Starting FastAPI backend..."
cd "$backendPath"
python -m uvicorn app:app --reload --port 5001 &
BACKEND_PID=$!
cd ..

echo "Starting frontend..."
npm run dev &
FRONTEND_PID=$!

echo ""
echo "======================================"
echo "Backend   → http://localhost:5001"
echo "Executor  → http://localhost:8000"
echo "Frontend  → http://localhost:5173"
echo "Redis     → localhost:6379"
echo "======================================"

# TIP: If docker fails, this command prints why:
# docker logs math-executor

wait