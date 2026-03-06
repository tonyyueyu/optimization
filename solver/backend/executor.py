import os
import shutil
import uuid
import glob
import time
import asyncio
import traceback
import uvicorn
import logging
from typing import Optional, Dict, List
from fastapi import FastAPI, UploadFile, File, HTTPException, Form
from pydantic import BaseModel

logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')
logger = logging.getLogger("executor")

logger.info("=== STATEFUL EXECUTOR v2.2 (Fixed ADC & NameErrors) ===")

isCloud = False

# --- Configuration ---
raw_bucket_name = os.getenv("GCS_BUCKET_NAME")
BUCKET_NAME = raw_bucket_name.strip('"\n\r ') if raw_bucket_name else None
# Use /tmp/session_data for environments like Cloud Run where only /tmp is writable
STORAGE_BASE = "/tmp/session_data" 
os.makedirs(STORAGE_BASE, exist_ok=True)

# --- Guarded imports ---
try:
    from kernel_manager import PersistentKernel
except Exception as e:
    logger.error(f"FATAL: Failed to import kernel_manager: {e}")
    traceback.print_exc()
    PersistentKernel = None

try:
    from google.cloud import storage
except Exception as e:
    logger.warning(f"WARNING: google.cloud.storage not available: {e}")
    storage = None

app = FastAPI()

# GLOBAL DICTIONARY - MUST BE DEFINED AT MODULE LEVEL
# This holds the active session kernels
kernels: Dict[str, any] = {} 
_storage_client = None

# ──────────────────────────────────────────────
# Helpers
# ──────────────────────────────────────────────

def get_storage_client():
    global _storage_client # Use storage_client for the backend file, _storage_client for the executor
    if _storage_client is None:
        try:
            # Explicitly load the JSON key if it is baked into the container
            if os.path.exists("gcs-key.json"):
                _storage_client = storage.Client.from_service_account_json("gcs-key.json")
            else:
                # Fallback just in case
                _storage_client = storage.Client(project="hippomath") 
        except Exception as e:
            logger.warning(f"WARNING: Could not create storage client: {e}")
            return None
    return _storage_client

def get_session_paths(session_id: str):
    """Create and return local directories for a session."""
    base = os.path.join(STORAGE_BASE, session_id)
    uploads = os.path.join(base, "uploads")
    exports = os.path.join(base, "exports")
    os.makedirs(uploads, exist_ok=True)
    os.makedirs(exports, exist_ok=True)
    return base, uploads, exports

def sync_uploads_from_gcs(session_id: str, local_upload_dir: str):
    """Download files from GCS to local so the kernel can access them."""
    client = get_storage_client()
    if not client or not BUCKET_NAME:
        return

    try:
        bucket = client.bucket(BUCKET_NAME)
        prefix = f"uploads/{session_id}/"
        blobs = list(bucket.list_blobs(prefix=prefix))

        for blob in blobs:
            filename = os.path.basename(blob.name)
            if not filename: continue
            local_path = os.path.join(local_upload_dir, filename)
            
            if not os.path.exists(local_path) or os.path.getsize(local_path) != blob.size:
                blob.download_to_filename(local_path)
                logger.info(f"  ↓ Synced from GCS: {filename}")
    except Exception as e:
        logger.warning(f"WARNING: Sync from GCS failed: {e}")

# ──────────────────────────────────────────────
# API Models
# ──────────────────────────────────────────────

class CodeRequest(BaseModel):
    code: str
    session_id: str
    timeout: int = 200

# ──────────────────────────────────────────────
# Endpoints
# ──────────────────────────────────────────────

@app.post("/upload")
async def upload_file(file: UploadFile = File(...), session_id: str = Form(...)):
    """Saves file to LOCAL uploads folder AND GCS bucket."""
    logger.info(f"📥 [/upload] Upload request received in executor: filename={file.filename}, session={session_id}")
    if not file.filename:
        raise HTTPException(status_code=400, detail="No filename provided")

    _, upload_dir, _ = get_session_paths(session_id)
    local_path = os.path.join(upload_dir, file.filename)

    # 1. Save Locally (Critical for current execution)
    try:
        content = await file.read()
        with open(local_path, "wb") as f:
            f.write(content)
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Failed to save locally: {e}")

    # 2. Upload to GCS (Critical for persistence across instance restarts)
    client = get_storage_client()
    gcs_status = "skipped"
    if client and BUCKET_NAME:
        try:
            bucket = client.bucket(BUCKET_NAME)
            blob = bucket.blob(f"uploads/{session_id}/{file.filename}")
            blob.upload_from_filename(local_path)
            gcs_status = "success"
        except Exception as e:
            logger.error(f"GCS Upload Error: {e}")
            gcs_status = f"error: {e}"

    return {
        "status": "success", 
        "filename": file.filename, 
        "gcs": gcs_status
    }

@app.post("/execute")
async def execute(request: CodeRequest):
    # Ensure global kernels dict is accessible
    global kernels 
    
    logger.info(f"⚡ [/execute] Execution requested for session_id={request.session_id}, timeout={request.timeout}s")
    
    session_root, upload_dir, export_dir = get_session_paths(request.session_id)

    # 1. Sync files from GCS (Disabled: files now accessed via URLs in prompt)
    # sync_uploads_from_gcs(request.session_id, upload_dir)

    # 2. Kernel Lifecycle
    if request.session_id not in kernels:
        if PersistentKernel is None:
            raise HTTPException(status_code=500, detail="Kernel manager unavailable")
        logger.info(f"Creating new kernel for session: {request.session_id}")
        kernels[request.session_id] = PersistentKernel()

    kernel = kernels[request.session_id]

    # 3. Environment Setup (Inject paths into the Python kernel)
    # We use raw strings r'' to avoid Windows path escaping issues if running locally
    setup_code = f"""
import os, sys, uuid
os.chdir(r'{os.path.abspath(session_root)}')
import matplotlib
matplotlib.use('Agg') # Prevent attempt to open windows
import matplotlib.pyplot as plt

os.chdir(r'{os.path.abspath(session_root)}')

# Override plt.show to save to our export directory
def _custom_show_shim():
    if plt.get_fignums():
        filename = f"auto_plot_{{uuid.uuid4().hex[:6]}}.png"
        save_path = os.path.join(r'{os.path.abspath(export_dir)}', filename)
        plt.savefig(save_path, bbox_inches='tight')
        plt.close() # Close to free memory and prevent duplicate saves

plt.show = _custom_show_shim
"""
    kernel.execute_code(setup_code)

    # 4. Clear old exports from this session's folder
    for f in os.listdir(export_dir):
        path = os.path.join(export_dir, f)
        try:
            shutil.rmtree(path) if os.path.isdir(path) else os.unlink(path)
        except: pass

    # 5. Execute code
    loop = asyncio.get_running_loop()
    try:
        result = await asyncio.wait_for(
            loop.run_in_executor(None, kernel.execute_code, request.code),
            timeout=request.timeout
        )
        
        output_parts = []
        if result.get("output"):
            output_parts.append(result["output"])
            
        stderr = result.get("error", "")        
        if stderr:
            # Check if this looks like a real Python Traceback
            is_real_exception = "Traceback (most recent call last)" in stderr or result.get("status") == "error"
            
            if not is_real_exception:
                # It's probably just a warning (e.g. Matplotlib font warnings, Pandas warnings)
                # Move it to the output stream so it's not red in the UI
                output_parts.append(f"\n--- System Logs ---\n{stderr}")
                result["error"] = None # Clear the error field
            else:
                # Keep it as an error
                result["error"] = stderr

        result["output"] = "\n".join(output_parts).strip()
        
        # 6. Collect results (files created by the code)
        # Assuming your code writes to 'exports/' relative to session_root
        exported_files = []
        client = get_storage_client()
        
        # Search BOTH session_root and export_dir for new images/files
        # But prioritize the exports folder
        search_paths = [export_dir, session_root]
        found_files = []
        for p in search_paths:
            found_files.extend([f for f in glob.glob(f"{p}/**/*", recursive=True) if os.path.isfile(f)])

        # Deduplicate and filter (optional: ignore hidden files)
        found_files = list(set(found_files))

        for filepath in found_files:
            fname = os.path.basename(filepath)
            
            # Skip python scripts or system files
            if fname.endswith(('.py', '.pyc')) or '__pycache__' in filepath:
                continue

            gcs_path = f"outputs/{request.session_id}/{uuid.uuid4().hex[:6]}_{fname}"
            
            if client and BUCKET_NAME:
                blob = client.bucket(BUCKET_NAME).blob(gcs_path)
                blob.upload_from_filename(filepath)
                
                # Check if it's an image to treat it as a "plot"
                is_image = fname.lower().endswith(('.png', '.jpg', '.jpeg', '.gif'))
                
                file_info = {"name": fname, "gcs_path": gcs_path}
                if is_image:
                    # Optional: If your backend expects Base64 for plots, 
                    # you might need to read the file and add it to result["plots"]
                    import base64
                    with open(filepath, "rb") as img_f:
                        if "plots" not in result: result["plots"] = []
                        result["plots"].append(base64.b64encode(img_f.read()).decode('utf-8'))
                
                exported_files.append(file_info)

        result["files"] = exported_files
        return result

    except asyncio.TimeoutError:
        return {"status": "error", "error": "Execution timed out"}
    except Exception as e:
        traceback.print_exc()
        return {"status": "error", "error": str(e)}

@app.get("/ping")
async def ping():
    return {"status": "alive"}

@app.delete("/cleanup/{session_id}")
async def cleanup_session(session_id: str):
    global kernels
    logger.info(f"🧹 [/cleanup/{session_id}] Cleanup requested.")
    # Remove kernel
    if session_id in kernels:
        try:
            kernels[session_id].cleanup()
        except:
            pass
        del kernels[session_id]
        
    # Delete local files
    try:
        session_root = os.path.join(STORAGE_BASE, session_id)
        if os.path.exists(session_root):
            shutil.rmtree(session_root)
    except Exception as e:
        logger.error(f"Failed to delete session folder {session_root}: {e}")
        
    return {"status": "success", "message": f"Session {session_id} cleaned up locally."}

@app.on_event("startup")
async def startup_event():
    # Start a background task to clean up old files/kernels
    asyncio.create_task(cleanup_janitor())

async def cleanup_janitor():
    """Simple janitor to clean up local storage every hour."""
    while True:
        await asyncio.sleep(3600)
        # Logic to remove folders in STORAGE_BASE older than 24h
        pass

if __name__ == "__main__":
    port = int(os.environ.get("PORT", 8080))
    uvicorn.run(app, host="0.0.0.0", port=port)