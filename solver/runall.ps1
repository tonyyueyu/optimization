# PowerShell equivalent of your Bash script with new terminals
$ErrorActionPreference = "Stop"

$backendPath = ".\backend"

Write-Host "Building Docker image for math-executor..."
docker build -t math-executor $backendPath

Write-Host "Restarting math-executor container..."
try { docker rm -f math-executor } catch {}
docker run -d `
  --name math-executor `
  -p 8000:8000 `
  math-executor

Write-Host "Starting Redis..."
try { docker rm -f my-redis } catch {}
docker run -d --name my-redis -p 6379:6379 redis

Write-Host "Starting FastAPI backend in a new terminal..."
Start-Process powershell -ArgumentList "-NoExit", "-Command", "cd '$backendPath'; python -m uvicorn app:app --reload --port 5001"

Write-Host "Starting frontend in a new terminal..."
Start-Process powershell -ArgumentList "-NoExit", "-Command", "npm run dev"

Write-Host ""
Write-Host "======================================"
Write-Host "Backend   → http://localhost:5001"
Write-Host "Executor  → http://localhost:8000"
Write-Host "Frontend  → http://localhost:5173"
Write-Host "Redis     → localhost:6379"
Write-Host "======================================"

Write-Host "TIP: If docker fails, check logs with: docker logs math-executor"
