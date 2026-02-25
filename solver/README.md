# Optimization Solver

An AI-powered application for formulating and solving mathematical optimization problems. It uses Google's gemini-3-flash-preview to generate and execute Python code in containerized kernels.

## Overview

This tool helps users solve optimization models by converting natural language prompts into executable Python code. It supports solvers like Pyomo, Gurobi, GLPK, and XGBoost. 

A key feature is the persistent execution context, which maintains state across multi-step conversations by keeping the underlying Python kernel alive between requests.

## Features

- **Natural Language Interface:** Describe optimization problems in plain text to get modeled and executed solutions.
- **Stateful Execution:** Maintains variables and data across chat prompts using a persistent Jupyter kernel.
- **Supported Paradigms:** Linear, Mixed-Integer, Non-Linear optimization, CAD modeling and analysis (via CadQuery), and standard tabular data analysis.
- **RAG Context:** Uses Pinecone to retrieve similar past formulations and guide the LLM's code generation.
- **File Uploads:** Upload CSV/Excel datasets to Google Cloud Storage (GCS) to be loaded directly into the solver environment.
- **UI:** React frontend with LaTeX rendering and collapsible execution steps.

## Architecture

The application is split into a frontend and two backend services:

1. **Frontend (React/Vite)**
   - Manages the chat UI, file uploads, and renders Server-Sent Events (SSE) streams.
   - Handles authentication via Clerk.
2. **API Backend (FastAPI)**
   - Orchestrates the LLM (Google Gemini) and RAG (Pinecone) queries.
   - Manages chat history using Firebase Realtime Database.
3. **Kernel Executor (FastAPI)**
   - Runs the generated Python code in a sandboxed environment.
   - Keeps Jupyter Kernels alive between requests to maintain session state.
   - Syncs session files with Google Cloud Storage.

## Tech Stack

- **Frontend:** React, Vite, Clerk, KaTeX
- **Backend:** FastAPI, Python, Jupyter Client, Firebase Admin SDK
- **AI/ML:** Google Gemini API, Pinecone
- **Infrastructure:** Docker, Google Cloud Run, Google Cloud Storage

## Getting Started

### Prerequisites

- Docker & Docker Compose
- Node.js 18+
- Python 3.10+
- Google Cloud Service Account credentials (for GCS)
- Gemini API Key
- Pinecone API Key
- Firebase API keys and project settings

### Environment Variables

Create a `.env` file in the project's root directory:

```env
GOOGLE_API_KEY=your_gemini_api_key
PINECONE_API_KEY=your_pinecone_api_key
GCS_BUCKET_NAME=your_gcs_bucket_name

# Firebase Credentials
FIREBASE_TYPE=service_account
FIREBASE_PROJECT_ID=...
FIREBASE_PRIVATE_KEY_ID=...
FIREBASE_PRIVATE_KEY="-----BEGIN PRIVATE KEY-----\n...\n-----END PRIVATE KEY-----\n"
FIREBASE_CLIENT_EMAIL=...
FIREBASE_CLIENT_ID=...
FIREBASE_AUTH_URI=...
FIREBASE_TOKEN_URI=...
FIREBASE_AUTH_PROVIDER_X509_CERT_URL=...
FIREBASE_CLIENT_X509_CERT_URL=...
FIREBASE_UNIVERSE_DOMAIN=...
FIREBASE_DB_URL=...
```

### Running Locally

Start the backend and executor services using Docker:

```bash
docker-compose up --build
```

Start the Vite frontend:

```bash
npm install
npm run dev
```

## Security Limits

- **Execution Timeouts:** Code execution is capped, and solver calls are configured with explicit time limits (e.g. `TimeLimit=30`).
- **Storage Limits:** Each session is restricted to a maximum storage quota (e.g., 1.5GB) to prevent disk exhaustion.
- **Cleanup:** A background process routinely deletes inactive sessions and their associated files from local disk and cloud storage.
