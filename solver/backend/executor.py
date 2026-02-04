import os
import shutil
import uvicorn
import asyncio
import glob
import uuid
import time
from fastapi import FastAPI, UploadFile, File, HTTPException, Form
from pydantic import BaseModel
from kernel_manager import PersistentKernel
from google.cloud import storage

# --- Configuration ---
BUCKET_NAME = os.getenv("GCS_BUCKET_NAME")
STORAGE_BASE = "session_data"  # Root for local session files
STORAGE_LIMIT_BYTES = 1.5 * 1024 * 1024 * 1024  # 1.5 GB
os.makedirs(STORAGE_BASE, exist_ok=True)

app = FastAPI()
kernel = PersistentKernel()
storage_client = None

# --- Models ---
class CodeRequest(BaseModel):
    code: str
    session_id: str
    timeout: int = 30

# --- Helpers ---
def get_storage_client():
    global storage_client
    if storage_client is None:
        try:
            storage_client = storage.Client()
        except:
            return None
    return storage_client

def get_session_paths(session_id: str):
    """Returns and creates the uploads and exports paths for a session."""
    base = os.path.join(STORAGE_BASE, session_id)
    uploads = os.path.join(base, "uploads")
    exports = os.path.join(base, "exports")
    os.makedirs(uploads, exist_ok=True)
    os.makedirs(exports, exist_ok=True)
    return base, uploads, exports

def get_local_session_usage(session_id: str):
    """Calculates total bytes used by a session on the Docker disk."""
    session_root = os.path.join(STORAGE_BASE, session_id)
    if not os.path.exists(session_root):
        return 0
    total = 0
    for dirpath, dirnames, filenames in os.walk(session_root):
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
        print(f"UPLOAD FAILED: {str(e)}")
        raise HTTPException(status_code=500, detail=f"Failed to save file: {str(e)}")

@app.post("/execute")
async def execute(request: CodeRequest):
    session_root, _, export_dir = get_session_paths(request.session_id)

    # 2. "Jail" the kernel into the session directory
    # This ensures Gemini's code can just use 'uploads/file.csv'
    abs_session_root = os.path.abspath(session_root)
    kernel.execute_code(f"import os; os.chdir('{abs_session_root}')")

    # 3. Run the user code
    loop = asyncio.get_running_loop()
    try:
        result = await asyncio.wait_for(
            loop.run_in_executor(None, kernel.execute_code, request.code), 
            timeout=request.timeout
        )

        # 4. Upload results to GCS for Signed URL delivery
        exported_files = []
        files_found = glob.glob(f"{export_dir}/*")
        client = get_storage_client()

        if files_found:
            for filepath in files_found:
                filename = os.path.basename(filepath)
                
                # Logic for GCS if available
                if BUCKET_NAME and client:
                    bucket = client.bucket(BUCKET_NAME)
                    run_id = uuid.uuid4().hex[:8]
                    blob_path = f"outputs/{request.session_id}/{run_id}_{filename}"
                    blob = bucket.blob(blob_path)
                    blob.upload_from_filename(filepath)
                    exported_files.append({"name": filename, "gcs_path": blob_path})
                else:
                    # LOCAL TESTING MODE: Just log that it happened
                    print(f"OFFLINE MODE: File {filename} generated but GCS upload skipped.")
                    # We send a dummy path so the backend doesn't crash
                    exported_files.append({"name": filename, "gcs_path": "local_test_mode"})
        
        result["files"] = exported_files
        return result

    except asyncio.TimeoutError:
        if hasattr(kernel, 'restart'): kernel.restart()
        return {"status": "error", "error": "Timeout"}
    except Exception as e:
        return {"status": "error", "error": str(e)}

@app.delete("/cleanup/{session_id}")
async def cleanup_session(session_id: str):
    """Wipes all local files for a session."""
    session_root = os.path.join(STORAGE_BASE, session_id)
    if os.path.exists(session_root):
        shutil.rmtree(session_root)
        return {"status": "success", "message": f"Session {session_id} wiped."}
    return {"status": "noop", "message": "Session directory did not exist."}

@app.get("/health")
async def health():
    return {"status": "ready"}

async def cleanup_old_sessions():
    """Delete folders older than 24 hours every hour."""
    while True:
        now = time.time()
        for session_folder in os.listdir(STORAGE_BASE):
            full_path = os.path.join(STORAGE_BASE, session_folder)
            # If folder hasn't been touched in 24 hours, wipe it
            if os.path.getmtime(full_path) < now - (24 * 3600):
                shutil.rmtree(full_path)
                print(f"Janitor: Cleaned up abandoned session {session_folder}")
        await asyncio.sleep(3600) # Run every hour

@app.on_event("startup")
async def startup_event():
    asyncio.create_task(cleanup_old_sessions()) 

if __name__ == "__main__":
    uvicorn.run(app, host="0.0.0.0", port=8000)