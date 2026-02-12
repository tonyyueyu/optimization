# HippoFlo

A comprehensive optimization solver platform featuring a Vite-based React frontend and a multi-service Python backend.

## Repository Structure

- **/solver**: The main application codebase.
  - `backend/`: Python services (API and Math Executor).
  - `src/`: React frontend source code.
- **/RAG**: Resources related to Retrieval-Augmented Generation.

---

## Getting Started (Local Development)

To get the application up and running on your local development server, follow the instructions below.

### Prerequisites

- **Docker** and **Docker Compose** installed on your machine.
- Access to Google Cloud Storage (GCS) if using features that require cloud storage.

### Build and Deploy

Run these commands from the **root directory** of the repository:

#### For macOS / Linux

```bash
cd solver
export DOCKER_DEFAULT_PLATFORM=linux/amd64
./runall.sh
```

#### For Windows (PowerShell)

```powershell
cd solver
.\runall.ps1
```

---

## Architecture

The application is composed of three main services:

| Service | Technology | Port | Description |
| :--- | :--- | :--- | :--- |
| **Frontend** | React + Vite | `5173` | The user interface for interacting with the solver. |
| **Backend** | Python (FastAPI/Flask) | `8000` | The main API and database interface. |
| **Executor** | Python | `8001` | Dedicated service for handling heavy math computations. |

## Configuration

Ensure you have the following files configured in the `solver` directory:

- `solver/backend/.env`: Environment variables for the backend and executor.
- `solver/gcs-key.json`: Required for Google Cloud Storage authentication.
- `solver/docker-compose.yml`: Orchestrates the containerized services.

## Available Scripts (in `/solver`)

- `./runall.sh`: Stops any running containers and rebuilds/restarts all services.
- `npm run dev`: Runs the frontend in development mode locally (requires manual setup of backend).

---

Developed as part of the Optimization Project.