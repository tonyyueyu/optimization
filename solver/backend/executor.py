import os
import shutil
import uvicorn
import asyncio
from fastapi import FastAPI, UploadFile, File, HTTPException
from pydantic import BaseModel
from kernel_manager import PersistentKernel

app = FastAPI()
kernel = PersistentKernel()

class CodeRequest(BaseModel):
    code: str
    timeout: int = 30

@app.post("/upload")
async def upload_file(file: UploadFile = File(...)):
    if not file.filename:
        raise HTTPException(status_code=400, detail="Empty filename")

    # --- FIX IS HERE: Force save to 'uploads' directory ---
    base_dir = os.getcwd()
    upload_dir = os.path.join(base_dir, "uploads")
    
    # Ensure folder exists
    os.makedirs(upload_dir, exist_ok=True)
    
    file_path = os.path.join(upload_dir, file.filename)

    try:
        with open(file_path, "wb") as buffer:
            shutil.copyfileobj(file.file, buffer)
            
        return {
            "status": "success",
            "filename": file.filename,
            "path": file_path, # Returns /app/uploads/filename
            "summary": f"File '{file.filename}' uploaded successfully."
        }
    except Exception as e:
        # Print error to logs so we can see it in Docker
        print(f"UPLOAD FAILED: {str(e)}")
        raise HTTPException(status_code=500, detail=f"Failed to save file: {str(e)}")

@app.post("/execute")
async def execute(request: CodeRequest):
    code = request.code
    timeout = request.timeout
    print(f"Executing: {code[:50]}...") 
    loop = asyncio.get_running_loop()
    try:
        result = await asyncio.wait_for(
            loop.run_in_executor(None, kernel.execute_code, code), 
            timeout=timeout
        )
        return result
    except asyncio.TimeoutError:
        if hasattr(kernel, 'restart'):
            kernel.restart()
        return {"status": "error", "error": "Timeout"}
    except Exception as e:
        return {"status": "error", "error": str(e)}

@app.get("/health")
async def health():
    return {"status": "ready"}

if __name__ == "__main__":
    # Ensure this port matches your Dockerfile/Compose (8000 internally)
    uvicorn.run(app, host="0.0.0.0", port=8000)