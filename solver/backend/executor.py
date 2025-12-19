import os
import shutil
import uvicorn
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

@app.post("/upload")
async def upload_file(file: UploadFile = File(...)):
    if not file.filename:
        raise HTTPException(status_code=400, detail="Empty filename")

    # Define save path (current working directory)
    save_directory = os.getcwd()
    file_path = os.path.join(save_directory, file.filename)

    try:
        # FastAPI uses 'spooled' temporary files, so we copy them to disk
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
    
    print(f"Executing: {code}")  # Log to Docker stdout
    
    # Run the code using your existing Logic
    # Note: If kernel.execute_code is blocking, it's fine for now, 
    # but in high-load async apps you'd typically await it or wrap it.
    try:
        result = kernel.execute_code(code)
        return result
    except Exception as e:
        # Gracefully handle kernel crashes or errors
        return {"status": "error", "error": str(e)}

@app.get("/health")
async def health():
    return {"status": "ready"}

if __name__ == "__main__":
    uvicorn.run(app, host="0.0.0.0", port=8000)