# -------------------------
# PowerShell script to start backend, Redis, Docker executor, and frontend
# -------------------------

# --- Paths ---
$backendPath = ".\backend"

# --- Step 1: Build and run math-executor Docker image ---
Write-Host "Building Docker image for math-executor..."
docker build -t math-executor $backendPath

Write-Host "Running math-executor container on port 8000..."
docker run -d --name math-executor -p 8000:8000 math-executor

# --- Step 2: Run Redis ---
# Check if Redis container exists
$redisContainer = docker ps -a --filter "name=my-redis" --format "{{.Names}}"
if ($redisContainer -eq "my-redis") {
    Write-Host "Redis container already exists. Starting it..."
    docker start my-redis
} else {
    Write-Host "Running Redis container on port 6379..."
    docker run -d --name my-redis -p 6379:6379 redis
}

# --- Step 3: Start FastAPI backend ---
Write-Host "Starting FastAPI backend on port 5000..."
Start-Process powershell -ArgumentList "-NoExit", "-Command", "cd $backendPath; python -m uvicorn app:app --reload --port 5000"

# --- Step 4: Start frontend ---
Write-Host "Starting frontend dev server..."
Start-Process powershell -ArgumentList "-NoExit", "-Command", "npm run dev"
