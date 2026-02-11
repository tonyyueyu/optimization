import os
import shutil
import uvicorn
import asyncio
import glob
import uuid
import time
from typing import Optional, Dict
from fastapi import FastAPI, UploadFile, File, HTTPException, Form
from pydantic import BaseModel
from kernel_manager import PersistentKernel # Assuming this class exists in your project
from google.cloud import storage

# --- Configuration ---
BUCKET_NAME = os.getenv("GCS_BUCKET_NAME")
STORAGE_BASE = "session_data"
STORAGE_LIMIT_BYTES = 1.5 * 1024 * 1024 * 1024  # 1.5 GB
os.makedirs(STORAGE_BASE, exist_ok=True)

app = FastAPI()

# --- NEW: Kernel Dictionary for Isolation ---
# Maps session_id -> PersistentKernel instance
kernels: Dict[str, PersistentKernel] = {}

storage_client = None

# --- Models ---
class CodeRequest(BaseModel):
    code: str
    session_id: str  # Made mandatory for isolation
    timeout: int = 120

# --- Helpers ---
def get_storage_client():
    global storage_client
    if storage_client is None:
        try:
            storage_client = storage.Client()
        except:
            return None
    return storage_client

def get_kernel(session_id: str) -> PersistentKernel:
    """Retrieves an existing kernel or creates a new one for the session."""
    if session_id not in kernels:
        print(f"Kernel Manager: Creating new kernel for session {session_id}")
        kernels[session_id] = PersistentKernel()
    return kernels[session_id]

def get_session_paths(session_id: str):
    base = os.path.join(STORAGE_BASE, session_id)
    uploads = os.path.join(base, "uploads")
    exports = os.path.join(base, "exports")
    os.makedirs(uploads, exist_ok=True)
    os.makedirs(exports, exist_ok=True)
    return base, uploads, exports

def get_local_session_usage(session_id: str):
    session_root = os.path.join(STORAGE_BASE, session_id)
    if not os.path.exists(session_root):
        return 0
    total = 0
    for dirpath, _, filenames in os.walk(session_root):
        for f in filenames:
            fp = os.path.join(dirpath, f)
            total += os.path.getsize(fp)
    return total

# --- Endpoints ---

@app.post("/upload")
async def upload_file(file: UploadFile = File(...), session_id: str = Form(...)):
    if not file.filename:
        raise HTTPException(status_code=400, detail="Empty filename")

    # 1. Check 1.5GB limit locally
    current_usage = get_local_session_usage(session_id)
    if current_usage + (file.size or 0) > STORAGE_LIMIT_BYTES:
        raise HTTPException(status_code=413, detail="Session storage limit (1.5GB) exceeded.")

    # 2. Save to session-specific uploads folder
    _, upload_dir, _ = get_session_paths(session_id)
    file_path = os.path.join(upload_dir, file.filename)

    try:
        with open(file_path, "wb") as buffer:
            shutil.copyfileobj(file.file, buffer)
        return {"status": "success", "filename": file.filename, "path": f"uploads/{file.filename}"}
    except Exception as e:
        print(f"UPLOAD FAILED for {session_id}: {str(e)}")
        raise HTTPException(status_code=500, detail=f"Failed to save file: {str(e)}")

# --- Endpoints ---

@app.post("/execute")
async def execute(request: CodeRequest):
    session_root, _, export_dir = get_session_paths(request.session_id)
    
    # 1. FIX: Clear local exports folder so buttons don't persist across steps
    for f in os.listdir(export_dir):
        path = os.path.join(export_dir, f)
        try:
            if os.path.isfile(path): os.unlink(path)
            elif os.path.isdir(path): shutil.rmtree(path)
        except Exception as e:
            print(f"Cleanup Error: {e}")

    # 2. Get the specific isolated kernel for this session
    session_kernel = get_kernel(request.session_id)

    # 3. Jail the kernel into the session directory
    abs_session_root = os.path.abspath(session_root)
    session_kernel.execute_code(f"import os; os.chdir('{abs_session_root}')")

    # 4. Run the user code
    loop = asyncio.get_running_loop()
    try:
        result = await asyncio.wait_for(
            loop.run_in_executor(None, session_kernel.execute_code, request.code), 
            timeout=request.timeout
        )

        # 5. Handle File Exports
        exported_files = []
        files_found = glob.glob(f"{export_dir}/*")
        client = get_storage_client()

        if files_found:
            for filepath in files_found:
                filename = os.path.basename(filepath)
                if BUCKET_NAME and client:
                    bucket = client.bucket(BUCKET_NAME)
                    run_id = uuid.uuid4().hex[:8]
                    blob_path = f"outputs/{request.session_id}/{run_id}_{filename}"
                    blob = bucket.blob(blob_path)
                    blob.upload_from_filename(filepath)
                    exported_files.append({"name": filename, "gcs_path": blob_path})
                else:
                    exported_files.append({"name": filename, "gcs_path": "local_test_mode"})
        
        result["files"] = exported_files
        return result

    except asyncio.TimeoutError:
        # If timeout, restart this specific kernel
        if hasattr(session_kernel, 'restart'): session_kernel.restart()
        return {"status": "error", "error": "Code execution timed out."}
    except Exception as e:
        return {"status": "error", "error": str(e)}

@app.delete("/cleanup/{session_id}")
async def cleanup_session(session_id: str):
    """Wipes files AND kills the Python process for this session."""
    # 1. Kill and remove the kernel from memory
    if session_id in kernels:
        k = kernels.pop(session_id)
        if hasattr(k, 'cleanup'): k.cleanup() # Assuming PersistentKernel has a shutdown method
        del k
    
    # 2. Wipe the files
    session_root = os.path.join(STORAGE_BASE, session_id)
    if os.path.exists(session_root):
        shutil.rmtree(session_root)
        return {"status": "success", "message": f"Session {session_id} wiped from disk and memory."}
    return {"status": "noop"}

async def cleanup_old_sessions():
    """Janitor: Periodically removes idle kernels and files to save RAM/Disk."""
    while True:
        await asyncio.sleep(3600) # Check every hour
        now = time.time()
        
        # We check the directory timestamps
        if not os.path.exists(STORAGE_BASE): continue
        
        for session_id in os.listdir(STORAGE_BASE):
            full_path = os.path.join(STORAGE_BASE, session_id)
            # If idle for 24 hours
            if os.path.getmtime(full_path) < now - (24 * 3600):
                print(f"Janitor: Cleaning up expired session {session_id}")
                # Use the existing cleanup logic
                await cleanup_session(session_id)

@app.on_event("startup")
async def startup_event():
    asyncio.create_task(cleanup_old_sessions())
    
if __name__ == "__main__":
    uvicorn.run(app, host="0.0.0.0", port=8000)