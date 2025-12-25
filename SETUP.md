# Setup Guide

This document outlines the commands needed to get the backend and frontend working.

## Architecture Overview

The application consists of:
1. **Backend (FastAPI)** - Port 5001 - Main API server
2. **Docker Executor** - Port 8000 - Code execution environment
3. **Frontend (React/Vite)** - Port 5173 - Web interface
4. **External Services**: Ollama, Pinecone, Firebase, Google Gemini API

## Prerequisites

- Python 3.10+ (with conda/mamba recommended)
- Node.js and npm
- Docker
- Ollama installed and running

## Step-by-Step Setup

### 1. Environment Variables

Create a `.env` file in `/Users/alexdu/optimization/solver/backend/` with the following variables:

```bash
# Google Gemini API
GOOGLE_API_KEY=your_google_api_key_here

# Pinecone API
PINECONE_API_KEY=your_pinecone_api_key_here

# Firebase Configuration
FIREBASE_TYPE=service_account
FIREBASE_PROJECT_ID=your_project_id
FIREBASE_PRIVATE_KEY_ID=your_private_key_id
FIREBASE_PRIVATE_KEY="-----BEGIN PRIVATE KEY-----\n...\n-----END PRIVATE KEY-----\n"
FIREBASE_CLIENT_EMAIL=your_client_email
FIREBASE_CLIENT_ID=your_client_id
FIREBASE_AUTH_URI=https://accounts.google.com/o/oauth2/auth
FIREBASE_TOKEN_URI=https://oauth2.googleapis.com/token
FIREBASE_AUTH_PROVIDER_X509_CERT_URL=https://www.googleapis.com/oauth2/v1/certs
FIREBASE_CLIENT_X509_CERT_URL=your_cert_url
FIREBASE_UNIVERSE_DOMAIN=googleapis.com
FIREBASE_DB_URL=https://your-project.firebaseio.com
```

### 2. Backend Setup

#### Option A: Using Conda/Mamba (Recommended - matches Docker environment)

```bash
cd /Users/alexdu/optimization/solver/backend

# Create conda environment from environment.yml
conda env create -f environment.yml
# OR if using mamba:
# mamba env create -f environment.yml

# Activate the environment
conda activate base  # or the environment name from environment.yml

# Install additional Python packages
pip install -r requirements.txt
```

#### Option B: Using pip only

```bash
cd /Users/alexdu/optimization/solver/backend

# Create virtual environment
python3.10 -m venv venv
source venv/bin/activate  # On Windows: venv\Scripts\activate

# Install packages
pip install -r requirements.txt
# Note: Some packages from environment.yml (like cadquery, ipopt, highs, glpk) 
# may need to be installed separately or via conda
```

### 3. Docker Executor Setup

```bash
cd /Users/alexdu/optimization/solver

# Build the Docker image
docker build -t math-executor ./backend

# Run the container (will be done automatically by runall.sh)
docker run -d --name math-executor -p 8000:8000 math-executor
```

### 4. Ollama Setup

The backend uses Ollama for embeddings. Make sure Ollama is installed and running:

```bash
# Install Ollama (if not already installed)
# Visit: https://ollama.ai/download

# Pull the required embedding model
ollama pull hf.co/CompendiumLabs/bge-base-en-v1.5-gguf

# Start Ollama (usually runs as a service)
# On macOS: ollama serve
```

### 5. Frontend Setup

```bash
cd /Users/alexdu/optimization/solver

# Install npm dependencies
npm install
```

### 6. Start Everything

#### Option A: Use the provided script (Linux/macOS)

```bash
cd /Users/alexdu/optimization/solver
chmod +x runall.sh
./runall.sh
```

#### Option B: Manual startup

**Terminal 1 - Docker Executor:**
```bash
cd /Users/alexdu/optimization/solver
docker rm -f math-executor 2>/dev/null || true
docker run -d --name math-executor -p 8000:8000 math-executor
```

**Terminal 2 - Backend:**
```bash
cd /Users/alexdu/optimization/solver/backend
# Activate your conda/venv environment first
python -m uvicorn app:app --reload --port 5001
```

**Terminal 3 - Frontend:**
```bash
cd /Users/alexdu/optimization/solver
npm run dev
```

#### Option C: PowerShell (Windows)

```powershell
cd /Users/alexdu/optimization/solver
.\runall.ps1
```

## Service URLs

Once everything is running:
- **Backend API**: http://localhost:5001
- **Docker Executor**: http://localhost:8000
- **Frontend**: http://localhost:5173
- **Database**: Firebase (cloud-based)

## Verification

1. **Check Docker Executor**: 
   ```bash
   curl http://localhost:8000/health
   ```
   Should return: `{"status":"ready"}`

2. **Check Backend**: 
   ```bash
   curl http://localhost:5001/docs
   ```
   Should show FastAPI documentation page

3. **Check Frontend**: 
   Open http://localhost:5173 in your browser

## Troubleshooting

### Docker Executor Issues
- Ensure Docker is running
- Check if port 8000 is available: `lsof -i :8000`
- View logs: `docker logs math-executor`

### Backend Issues
- Verify `.env` file exists and has all required variables
- Check Python environment is activated
- Ensure all dependencies are installed: `pip list`
- Check if port 5001 is available: `lsof -i :5001`

### Ollama Issues
- Verify Ollama is running: `ollama list`
- Check if the embedding model is available
- Test embedding: `ollama embed hf.co/CompendiumLabs/bge-base-en-v1.5-gguf "test"`

### Frontend Issues
- Clear node_modules and reinstall: `rm -rf node_modules && npm install`
- Check if port 5173 is available: `lsof -i :5173`

## Dependencies Summary

### Backend Python Packages (requirements.txt)
- fastapi, uvicorn
- google-generativeai (Gemini API)
- ollama (embeddings)
- pinecone (vector database)
- firebase-admin (database)
- python-dotenv (environment variables)
- redis, pydantic, python-multipart

### Backend Conda Packages (environment.yml)
- Python 3.10
- numpy, scipy, pandas, sympy, matplotlib
- cvxpy, pyomo (optimization)
- cadquery (CAD geometry)
- ipopt, highs, glpk (solvers)
- jupyter_client, ipykernel (kernel management)

### Frontend Packages
- React 19.2.0
- Vite 7.2.4
- Firebase SDK
- Clerk (authentication)
- React OAuth Google


