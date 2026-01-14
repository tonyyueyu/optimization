import os
import shutil
import uvicorn
import asyncio
import concurrent.futures
from fastapi import FastAPI, UploadFile, File, HTTPException
from pydantic import BaseModel
from kernel_manager import PersistentKernel

# Initialize FastAPI
app = FastAPI()

# Single global kernel
kernel = PersistentKernel()

# Pydantic model for request validation
class CodeRequest(BaseModel):
    code: str
    timeout: int = 30  # Allow user to specify timeout, default to 30s

@app.post("/upload")
async def upload_file(file: UploadFile = File(...)):
    if not file.filename:
        raise HTTPException(status_code=400, detail="Empty filename")

    save_directory = os.getcwd()
    file_path = os.path.join(save_directory, file.filename)

    try:
        with open(file_path, "wb") as buffer:
            shutil.copyfileobj(file.file, buffer)
            
        return {
            "status": "success",
            "filename": file.filename,
            "path": file_path,
            "summary": f"File '{file.filename}' successfully uploaded to {file_path}."
        }
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Failed to save file: {str(e)}")

@app.post("/execute")
async def execute(request: CodeRequest):
    code = request.code
    timeout = request.timeout
    
    print(f"Executing with {timeout}s limit: {code[:50]}...") 
    
    loop = asyncio.get_running_loop()

    try:
        result = await asyncio.wait_for(
            loop.run_in_executor(None, kernel.execute_code, code), 
            timeout=timeout
        )
        return result

    except asyncio.TimeoutError:
        print("Timeout reached. Restarting kernel...")
        
        if hasattr(kernel, 'restart'):
            kernel.restart()
        else:

            try:
                kernel.shutdown() 
                kernel.start()
            except:
                print("Could not cleanly restart kernel.")

        return {
            "status": "error", 
            "error": f"Execution timed out after {timeout} seconds. The kernel has been restarted to free up resources. State has been lost."
        }

    except Exception as e:
        return {"status": "error", "error": str(e)}

@app.get("/health")
async def health():
    return {"status": "ready"}

@app.post("/restart")
async def restart_kernel():
    """Manual endpoint to restart kernel if things get weird"""
    if hasattr(kernel, 'restart'):
        kernel.restart()
        return {"status": "success", "message": "Kernel restarted"}
    return {"status": "error", "message": "Kernel does not support restart"}

if __name__ == "__main__":
    uvicorn.run(app, host="0.0.0.0", port=8000)