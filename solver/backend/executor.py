# executor.py — Stateful executor with Cloud Run session affinity
import os
import shutil
import uuid
import glob
import time
import asyncio
import traceback
import uvicorn
from typing import Optional, Dict, List
from fastapi import FastAPI, UploadFile, File, HTTPException, Form
from pydantic import BaseModel

print("=== STATEFUL EXECUTOR v2 (Session Affinity) ===")

# --- Guarded imports ---
try:
    from kernel_manager import PersistentKernel
except Exception as e:
    print(f"FATAL: Failed to import kernel_manager: {e}")
    traceback.print_exc()
    PersistentKernel = None

try:
    from google.cloud import storage
except Exception as e:
    print(f"WARNING: google.cloud.storage not available: {e}")
    storage = None

# --- Configuration ---
BUCKET_NAME = os.getenv("GCS_BUCKET_NAME")
STORAGE_BASE = "session_data"
STORAGE_LIMIT_BYTES = 1.5 * 1024 * 1024 * 1024
os.makedirs(STORAGE_BASE, exist_ok=True)

app = FastAPI()

# Stateful: kernels persist across requests (session affinity keeps them on same instance)
kernels: Dict[str, "PersistentKernel"] = {}
_storage_client = None


# ──────────────────────────────────────────────
# GCS Client
# ──────────────────────────────────────────────

def get_gcs_client():
    global _storage_client
    if _storage_client is None and storage is not None:
        try:
            _storage_client = storage.Client()
            print("✅ GCS Storage Client initialized")
        except Exception as e:
            print(f"WARNING: Could not create storage client: {e}")
            return None
    return _storage_client


# ──────────────────────────────────────────────
# GCS Helpers
# ──────────────────────────────────────────────

def sync_uploads_from_gcs(session_id: str, local_upload_dir: str):
    """
    Download uploaded files from GCS to the session's local uploads/ folder.
    Skips files that already exist locally with the same size.
    Called before each execution to pick up any new uploads.
    """
    client = get_gcs_client()
    if not client or not BUCKET_NAME:
        print("WARNING: GCS not available, skipping upload sync")
        return

    try:
        bucket = client.bucket(BUCKET_NAME)
        prefix = f"uploads/{session_id}/"
        blobs = list(bucket.list_blobs(prefix=prefix))

        for blob in blobs:
            filename = blob.name[len(prefix):]
            if not filename or filename.endswith("/"):
                continue

            local_path = os.path.join(local_upload_dir, filename)
            os.makedirs(os.path.dirname(local_path), exist_ok=True)

            # Skip if already downloaded and same size
            if os.path.exists(local_path) and os.path.getsize(local_path) == blob.size:
                continue

            blob.download_to_filename(local_path)
            print(f"  ↓ Synced: {blob.name} → {local_path} ({blob.size} bytes)")

    except Exception as e:
        print(f"WARNING: GCS sync failed: {e}")
        traceback.print_exc()


def upload_exports_to_gcs(session_id: str, export_dir: str) -> List[Dict]:
    """Upload any files in the exports/ folder to GCS and return their paths."""
    client = get_gcs_client()

    if not os.path.exists(export_dir):
        return []

    files_found = glob.glob(f"{export_dir}/**/*", recursive=True)
    files_found = [f for f in files_found if os.path.isfile(f)]

    if not files_found:
        return []

    exported = []
    if client and BUCKET_NAME:
        bucket = client.bucket(BUCKET_NAME)
        for filepath in files_found:
            filename = os.path.basename(filepath)
            run_id = uuid.uuid4().hex[:8]
            gcs_path = f"outputs/{session_id}/{run_id}_{filename}"
            try:
                blob = bucket.blob(gcs_path)
                blob.upload_from_filename(filepath)
                exported.append({"name": filename, "gcs_path": gcs_path})
                print(f"  ↑ Exported: {filepath} → gs://{BUCKET_NAME}/{gcs_path}")
            except Exception as e:
                print(f"WARNING: Failed to upload {filepath}: {e}")
    else:
        for filepath in files_found:
            exported.append({
                "name": os.path.basename(filepath),
                "gcs_path": "local_test_mode"
            })

    return exported


def get_session_gcs_usage(session_id: str) -> int:
    """Check total bytes used by this session in GCS."""
    client = get_gcs_client()
    if not client or not BUCKET_NAME:
        return 0
    try:
        bucket = client.bucket(BUCKET_NAME)
        blobs = bucket.list_blobs(prefix=f"uploads/{session_id}/")
        return sum(blob.size for blob in blobs if blob.size)
    except Exception:
        return 0


# ──────────────────────────────────────────────
# Session & Kernel Helpers
# ──────────────────────────────────────────────

def get_session_paths(session_id: str):
    """Create and return local directories for a session."""
    base = os.path.join(STORAGE_BASE, session_id)
    uploads = os.path.join(base, "uploads")
    exports = os.path.join(base, "exports")
    os.makedirs(uploads, exist_ok=True)
    os.makedirs(exports, exist_ok=True)
    return base, uploads, exports


def get_kernel(session_id: str) -> "PersistentKernel":
    """Get or create a persistent kernel for a session."""
    if PersistentKernel is None:
        raise HTTPException(
            status_code=503,
            detail="Kernel manager not available — check container logs"
        )
    if session_id not in kernels:
        print(f"[{session_id}] Creating new persistent kernel")
        kernels[session_id] = PersistentKernel()
    return kernels[session_id]


def get_local_session_usage(session_id: str) -> int:
    """Calculate total bytes used by a session on local disk."""
    session_root = os.path.join(STORAGE_BASE, session_id)
    if not os.path.exists(session_root):
        return 0
    total = 0
    for dirpath, _, filenames in os.walk(session_root):
        for f in filenames:
            fp = os.path.join(dirpath, f)
            try:
                total += os.path.getsize(fp)
            except OSError:
                pass
    return total


# ──────────────────────────────────────────────
# API Models
# ──────────────────────────────────────────────

class CodeRequest(BaseModel):
    code: str
    session_id: str
    timeout: int = 120


# ──────────────────────────────────────────────
# Endpoints
# ──────────────────────────────────────────────

@app.get("/")
async def health():
    return {
        "status": "ok",
        "version": "stateful-v2-affinity",
        "kernel_available": PersistentKernel is not None,
        "storage_available": storage is not None,
        "bucket": BUCKET_NAME,
        "active_kernels": len(kernels),
    }


@app.post("/upload")
async def upload_file(file: UploadFile = File(...), session_id: str = Form(...)):
    """
    Upload a file directly to GCS.
    Note: app.py now uploads to GCS directly, so this endpoint is a fallback.
    """
    if not file.filename:
        raise HTTPException(status_code=400, detail="Empty filename")

    client = get_gcs_client()
    if not client or not BUCKET_NAME:
        # Fallback: save locally only
        _, upload_dir, _ = get_session_paths(session_id)
        file_path = os.path.join(upload_dir, file.filename)
        try:
            content = await file.read()
            with open(file_path, "wb") as buffer:
                buffer.write(content)
            return {"status": "success", "filename": file.filename, "path": f"uploads/{file.filename}"}
        except Exception as e:
            raise HTTPException(status_code=500, detail=str(e))

    # Check storage limit
    current_usage = get_session_gcs_usage(session_id)
    file_content = await file.read()
    if current_usage + len(file_content) > STORAGE_LIMIT_BYTES:
        raise HTTPException(status_code=413, detail="Session storage limit (1.5GB) exceeded.")

    try:
        bucket = client.bucket(BUCKET_NAME)
        gcs_path = f"uploads/{session_id}/{file.filename}"
        blob = bucket.blob(gcs_path)
        blob.upload_from_string(file_content, content_type=file.content_type)
        print(f"  ↑ Upload: {file.filename} → gs://{BUCKET_NAME}/{gcs_path}")

        return {
            "status": "success",
            "filename": file.filename,
            "path": f"uploads/{file.filename}"
        }
    except Exception as e:
        print(f"UPLOAD FAILED: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@app.post("/execute")
async def execute(request: CodeRequest):
    """
    Execute code in a persistent kernel.
    Session affinity ensures the same session always hits this instance.

    Flow:
    1. Sync uploads from GCS → local (picks up new files)
    2. Clear old exports
    3. Get/create persistent kernel
    4. Set working directory
    5. Run code
    6. Upload exports to GCS
    7. Return result (kernel stays alive for next step)
    """
    session_root, upload_dir, export_dir = get_session_paths(request.session_id)

    # 1) Sync uploads from GCS (picks up new files since last execution)
    sync_uploads_from_gcs(request.session_id, upload_dir)

    # 2) Clear old exports from previous step
    for f in os.listdir(export_dir):
        path = os.path.join(export_dir, f)
        try:
            if os.path.isfile(path):
                os.unlink(path)
            elif os.path.isdir(path):
                shutil.rmtree(path)
        except Exception as e:
            print(f"Export cleanup error: {e}")

    # 3) Get persistent kernel (creates if first request for this session)
    session_kernel = get_kernel(request.session_id)

    # 4) Set working directory
    abs_session_root = os.path.abspath(session_root)
    session_kernel.execute_code(f"import os; os.chdir('{abs_session_root}')")

    # 5) Run code with timeout
    loop = asyncio.get_running_loop()
    try:
        result = await asyncio.wait_for(
            loop.run_in_executor(None, session_kernel.execute_code, request.code),
            timeout=request.timeout
        )

        # 6) Upload exports to GCS
        exported_files = upload_exports_to_gcs(request.session_id, export_dir)
        result["files"] = exported_files

        print(f"[{request.session_id}] Done. Output: {str(result.get('output', ''))[:200]}")
        return result

    except asyncio.TimeoutError:
        print(f"[{request.session_id}] TIMEOUT after {request.timeout}s")
        # Restart kernel to kill stuck execution
        try:
            if hasattr(session_kernel, 'restart'):
                session_kernel.restart()
            else:
                # Kill and recreate
                if hasattr(session_kernel, 'cleanup'):
                    session_kernel.cleanup()
                kernels[request.session_id] = PersistentKernel()
        except Exception as restart_err:
            print(f"[{request.session_id}] Kernel restart failed: {restart_err}")
            kernels.pop(request.session_id, None)

        return {
            "status": "error",
            "output": "",
            "error": f"Code execution timed out after {request.timeout} seconds.",
            "plots": [],
            "files": []
        }
    except Exception as e:
        print(f"[{request.session_id}] ERROR: {e}")
        traceback.print_exc()
        return {
            "status": "error",
            "output": "",
            "error": str(e),
            "plots": [],
            "files": []
        }


@app.delete("/cleanup/{session_id}")
async def cleanup_session(session_id: str):
    """
    Clean up everything for a session:
    - Kill persistent kernel
    - Delete local files
    - Delete GCS files
    """
    cleaned = []

    # 1) Kill kernel
    if session_id in kernels:
        k = kernels.pop(session_id)
        try:
            if hasattr(k, 'cleanup'):
                k.cleanup()
            del k
            cleaned.append("kernel")
        except Exception as e:
            print(f"Kernel cleanup error: {e}")

    # 2) Delete local files
    session_root = os.path.join(STORAGE_BASE, session_id)
    if os.path.exists(session_root):
        shutil.rmtree(session_root, ignore_errors=True)
        cleaned.append("local_files")

    # 3) Delete GCS files
    client = get_gcs_client()
    if client and BUCKET_NAME:
        try:
            bucket = client.bucket(BUCKET_NAME)
            deleted_count = 0
            for prefix in [f"uploads/{session_id}/", f"outputs/{session_id}/"]:
                blobs = list(bucket.list_blobs(prefix=prefix))
                for blob in blobs:
                    blob.delete()
                    deleted_count += 1
            if deleted_count > 0:
                cleaned.append(f"gcs({deleted_count} files)")
        except Exception as e:
            print(f"GCS cleanup error: {e}")

    message = f"Cleaned: {', '.join(cleaned)}" if cleaned else "Nothing to clean"
    print(f"[{session_id}] {message}")
    return {"status": "success", "message": message}


# ──────────────────────────────────────────────
# Background Janitor — cleans up abandoned sessions
# ──────────────────────────────────────────────

async def cleanup_old_sessions():
    """Periodically clean up sessions that haven't been touched in 24 hours."""
    while True:
        await asyncio.sleep(3600)  # Run every hour
        now = time.time()
        max_age = 24 * 3600  # 24 hours

        if not os.path.exists(STORAGE_BASE):
            continue

        stale_sessions = []
        for session_id in os.listdir(STORAGE_BASE):
            full_path = os.path.join(STORAGE_BASE, session_id)
            if not os.path.isdir(full_path):
                continue
            try:
                last_modified = os.path.getmtime(full_path)
                if last_modified < now - max_age:
                    stale_sessions.append(session_id)
            except OSError:
                continue

        for session_id in stale_sessions:
            print(f"Janitor: Cleaning up stale session {session_id}")
            try:
                await cleanup_session(session_id)
            except Exception as e:
                print(f"Janitor error for {session_id}: {e}")


@app.on_event("startup")
async def startup_event():
    port = os.environ.get('PORT', '8080')
    print(f"=== Executor starting on port {port} ===")
    print(f"  Kernel available: {PersistentKernel is not None}")
    print(f"  Storage available: {storage is not None}")
    print(f"  Bucket: {BUCKET_NAME}")
    asyncio.create_task(cleanup_old_sessions())


if __name__ == "__main__":
    port = int(os.environ.get("PORT", 8080))
    uvicorn.run(app, host="0.0.0.0", port=port)