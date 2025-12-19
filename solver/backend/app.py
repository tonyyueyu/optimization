import os
import json
import requests
from dotenv import load_dotenv
# Added UploadFile, File, Form to imports
from fastapi import FastAPI, HTTPException, UploadFile, File, Form
from fastapi.middleware.cors import CORSMiddleware 
from fastapi.responses import StreamingResponse
from pydantic import BaseModel
from typing import Optional, List, Dict, Any
import ollama
from pinecone import Pinecone
import google.generativeai as genai
from history_manager import HistoryManager
import asyncio

# -- CONFIGURATION --
load_dotenv()
GOOGLE_API_KEY = os.getenv("GOOGLE_API_KEY")
PINECONE_API_KEY = os.getenv("PINECONE_API_KEY")

# Split URL to easily access base and execute endpoints
EXECUTOR_HOST = "http://localhost:8000"
EXECUTOR_URL = f"{EXECUTOR_HOST}/execute"

DISABLE_GEMINI = False # Set to True to disable Gemini generation for debugging

if not GOOGLE_API_KEY:
    raise ValueError("No API key found. Check your .env file.")

genai.configure(api_key=GOOGLE_API_KEY)

pc = Pinecone(api_key=PINECONE_API_KEY)
index_name = "math-questions"
index = pc.Index(index_name)

CHAT_MODEL_NAME = "gemini-2.5-flash"
EMBEDDING_MODEL_NAME = "hf.co/CompendiumLabs/bge-base-en-v1.5-gguf"

history_manager = HistoryManager()

# --- FastAPI app ---
app = FastAPI() 

# CORS Configuration
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["GET", "POST", "PUT", "DELETE", "OPTIONS", "PATCH"],
    allow_headers=["*"],
    expose_headers=["*"],
)

# -------------------- Pydantic Models --------------------
class RetrieveRequest(BaseModel):
    query: str

class SolveRequest(BaseModel):
    problem: str = ""
    second_problem: str = ""
    user_query: str
    user_id: Optional[str] = None 

class ChatHistoryRequest(BaseModel):
    id: str
    limit: Optional[int] = 50 

class ClearHistoryRequest(BaseModel):
    id: str

class SaveMessageRequest(BaseModel):
    user_id: str
    message: Dict[str, Any]


# -------------------- Helper Functions --------------------
def send_sse_event(event_type: str, data: dict) -> str:
    """Format data as Server-Sent Event"""
    return f"event: {event_type}\ndata: {json.dumps(data)}\n\n"


# -------------------- API Endpoints --------------------

@app.post("/api/upload")
async def upload_proxy(file: UploadFile = File(...), user_id: str = Form(...)):
    """
    Receives file from React, forwards it to Docker container.
    """
    try:
        # Read the file content into memory
        file_content = await file.read()
        
        # Prepare the file to send to the Docker container
        files_to_send = {
            'file': (file.filename, file_content, file.content_type)
        }
        
        # Forward request to Docker (Executor)
        # Note: We point to port 8000/upload
        print(f"Forwarding file {file.filename} to Docker executor...")
        response = requests.post(f"{EXECUTOR_HOST}/upload", files=files_to_send)
        
        if response.status_code != 200:
            raise HTTPException(status_code=response.status_code, detail=f"Docker Upload Failed: {response.text}")

        # Return the Docker container's response back to the Frontend
        return response.json()

    except requests.exceptions.ConnectionError:
        raise HTTPException(status_code=503, detail="Could not connect to Docker execution environment")
    except Exception as e:
        print(f"Upload error: {e}")
        raise HTTPException(status_code=500, detail=str(e))

@app.post("/api/retrieve")
async def retrieve(data: RetrieveRequest):
    query = data.query.strip()
    if not query:
        raise HTTPException(status_code=400, detail="Query is required")
    
    try:
        print(f"Embedding query with: {EMBEDDING_MODEL_NAME}")
        
        # Check if Ollama is accessible
        try:
            embed_resp = ollama.embed(model=EMBEDDING_MODEL_NAME, input=query)
            query_embed = embed_resp["embeddings"][0]
        except Exception as ollama_error:
            error_msg = f"Ollama embedding failed: {str(ollama_error)}"
            print(f"Warning: {error_msg}")
            print("Ollama is not running. Returning empty results.")
            return []
        
        # Check if Pinecone index is accessible
        try:
            results = index.query(vector=query_embed, top_k=2, include_metadata=True)
        except Exception as pinecone_error:
            error_msg = f"Pinecone query failed: {str(pinecone_error)}"
            print(f"Retrieval Error: {error_msg}")
            raise HTTPException(status_code=503, detail=error_msg)

        res = []
        fetched_ids = []
        for match in results.get("matches", []):
            metadata_json = match.get("metadata", {}).get("json")
            if metadata_json:
                try:
                    obj = json.loads(metadata_json)
                    prob_id = obj.get("id")
                    if prob_id:
                        fetched_ids.append(prob_id)
                    res.append({
                        "score": match["score"],
                        "id": obj.get("id"),
                        "problem": obj.get("problem"),
                        "solution": obj.get("solution"),
                        "steps": obj.get("steps"),
                    })
                except json.JSONDecodeError:
                    continue
        print(f"DEBUG: Fetched Similar Problem IDs: {fetched_ids}")
        return res 
    except HTTPException:
        raise
    except Exception as e:
        error_msg = f"Retrieval failed: {str(e)}"
        print(f"Retrieval Error: {error_msg}")
        raise HTTPException(status_code=500, detail=error_msg)


@app.post("/api/solve")
async def solve(data: SolveRequest):
    user_query = data.user_query.strip()
    if not user_query:
        raise HTTPException(status_code=400, detail="User query is required")

    problem1 = data.problem
    problem2 = data.second_problem
    user_id = data.user_id

    async def stream_solution():
        step_history = []
        if DISABLE_GEMINI:
            print("DEBUG: Gemini generation disabled via code.")
            
            # Emulate a quick response so frontend finishes gracefully
            yield send_sse_event("step_start", {
                "step_number": 1,
                "status": "disabled"
            })
            
            yield send_sse_event("executing", {
                "step_number": 1,
                "code": "# Gemini generation is currently disabled for debugging.\nprint('Generation disabled')"
            })

            yield send_sse_event("done", {
                "total_steps": 0,
                "steps": []
            })
            return
        else:
            finished = False
            code_output = "None (Start of problem)"
            max_steps = 10
            current_loop = 0

            to_do = []
            
            model = genai.GenerativeModel(
                model_name=CHAT_MODEL_NAME,
                generation_config={"response_mime_type": "application/json"},
            )
            chat_session = model.start_chat(history=[])
        
            # Save user message to history
            if user_id:
                history_manager.save_message(user_id, {
                    "role": "user",
                    "content": user_query,
                    "type": "text"
                })

            while not finished and current_loop < max_steps:
                step_number = current_loop + 1
                
                yield send_sse_event("step_start", {
                    "step_number": step_number,
                    "status": "generating"
                })

                prompt = f"""
                You are a Math Optimization Code Solver. Follow the reference examples to solve the user's problem step-by-step by generating Python code snippets. DO NOT use libraries outside of the reference examples unless ABSOLUTELY necessary!
                
                GOAL: Solve this problem: "{user_query}"
                
                REFERENCE EXAMPLES:
                1. {problem1}
                2. {problem2}

                CURRENT STATUS:
                History of steps taken: {json.dumps(step_history)}
                Original to-do list (use this as reference; LLM may update this in its "to_do" output): {json.dumps(to_do)}
                Output of the LAST executed code block: {code_output}

                INSTRUCTION:
                1. At the very first step, plan the full problem as a complete to-do list and include it in the "to_do" field.
                2. For subsequent steps, validate the last executed step based on the code output.
                3. Update the to-do list as needed, reflecting completed tasks or new tasks.
                4. Generate the NEXT step. Use the description section as a scratchpad and write your reasoning verbosely before writing code.
                5. Output strict JSON following the schema.
                6. ONLY use the libraries that the reference example used, unless ABSOLUTELY necessary.
                7. CLOSELY follow the reference examples in style, formatting, and approach.

                JSON SCHEMA:
                {{
                    "step_id": integer,
                    "description": "string",
                    "code": "python code string",
                    "to_do": ["string", "string", ...],
                    "is_final_step": boolean
                }}
                """
                
                print(f"--- Gemini Generating Step {step_number} (Streaming) ---")
                print(f"Prompt: {prompt}")
                
                try:
                    response = chat_session.send_message(prompt, stream=True)
                    accumulated_text = ""
                    
                    for chunk in response:
                        if chunk.text:
                            accumulated_text += chunk.text
                            yield send_sse_event("token", {
                                "step_number": step_number,
                                "text": chunk.text,
                                "accumulated": accumulated_text
                            })
                            await asyncio.sleep(0)
                    
                    step_data = json.loads(accumulated_text)
                    
                    yield send_sse_event("generation_complete", {
                        "step_number": step_number,
                        "step_data": step_data
                    })
                    
                except json.JSONDecodeError as e:
                    yield send_sse_event("error", {
                        "message": f"Failed to parse AI response as JSON: {str(e)}",
                        "raw_response": accumulated_text
                    })
                    return
                except Exception as e:
                    yield send_sse_event("error", {
                        "message": f"Failed to generate step from AI: {str(e)}"
                    })
                    return

                yield send_sse_event("executing", {
                    "step_number": step_number,
                    "code": step_data.get("code", "")
                })

                print(f"Sending code to Docker: {step_data.get('code')}")
                try:
                    docker_response = requests.post(
                        EXECUTOR_URL,
                        json={"code": step_data.get("code", "")},
                        timeout=30,
                    )
                    if docker_response.status_code == 200:
                        execution_result = docker_response.json()
                    else:
                        execution_result = {
                            "output": "",
                            "error": f"Docker API Error: {docker_response.status_code}",
                        }
                except requests.exceptions.ConnectionError:
                    execution_result = {
                        "output": "",
                        "error": "Could not connect to Docker container. Is it running?",
                    }

                code_output = execution_result["output"]
                if execution_result["error"]:
                    code_output += f"\nERROR: {execution_result['error']}"

                full_step_record = {
                    "step_id": step_data.get("step_id"),
                    "description": step_data.get("description"),
                    "code": step_data.get("code"),
                    "output": execution_result["output"],
                    "error": execution_result["error"],
                }
                step_history.append(full_step_record)

                to_do = step_data.get("to_do", to_do) 
                print(to_do)

                yield send_sse_event("step_complete", {
                    "step": full_step_record,
                    "step_number": step_number
                })

                if step_data.get("is_final_step", False):
                    finished = True

                current_loop += 1

            # Save assistant response to history
            if user_id and step_history:
                assistant_message = {
                    "role": "assistant",
                    "type": "steps",
                    "title": "Solution Steps",
                    "summary": "",
                    "steps": step_history
                }
                history_manager.save_message(user_id, assistant_message)

            yield send_sse_event("done", {
                "total_steps": len(step_history),
                "steps": step_history
            })

    return StreamingResponse(
        stream_solution(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "Connection": "keep-alive",
            "X-Accel-Buffering": "no",
        }
    )


# -------------------- REDIS Chat History Endpoints --------------------
@app.post("/api/chathistory")
async def get_chat_history(data: ChatHistoryRequest):
    """Fetch chat history for a user."""
    user_id = data.id.strip()
    
    if not user_id:
        raise HTTPException(status_code=400, detail="User ID is required")
    
    try:
        messages = history_manager.fetch_user_history(user_id)
        
        return {"history": messages, "count": len(messages)}
    
    except Exception as e:
        print(f"Error fetching chat history: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@app.post("/api/chathistory/clear")
async def clear_chat_history(data: ClearHistoryRequest):
    """Clear all chat history for a user."""
    user_id = data.id.strip()
    
    if not user_id:
        raise HTTPException(status_code=400, detail="User ID is required")
    
    try:
        success = history_manager.clear_user_history(user_id)
        return {"success": success, "message": "History cleared" if success else "Failed to clear"}
    
    except Exception as e:
        print(f"Error clearing chat history: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@app.post("/api/chathistory/save")
async def save_chat_message(data: SaveMessageRequest):
    """Manually save a message to history."""
    try:
        chat_id = history_manager.save_message(data.user_id, data.message)
        return {"success": True, "chat_id": chat_id}
    
    except Exception as e:
        print(f"Error saving message: {e}")
        raise HTTPException(status_code=500, detail=str(e))


# -------------------- Run --------------------
# Run with: uvicorn app:app --reload --port 5001