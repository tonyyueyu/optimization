import os
import json
import httpx 
import asyncio
from dotenv import load_dotenv
from fastapi import FastAPI, HTTPException, UploadFile, File, Form
from fastapi.middleware.cors import CORSMiddleware 
from fastapi.responses import StreamingResponse
from pydantic import BaseModel
from typing import Optional, List, Dict, Any
import ollama
from pinecone import Pinecone
import json_repair
from history_manager import HistoryManager

# --- NEW SDK IMPORTS ---
from google import genai
from google.genai import types
# -----------------------

# -- CONFIGURATION --
load_dotenv()
GOOGLE_API_KEY = os.getenv("GOOGLE_API_KEY")
PINECONE_API_KEY = os.getenv("PINECONE_API_KEY")

# Split URL to easily access base and execute endpoints
EXECUTOR_HOST = "http://localhost:8000"
EXECUTOR_URL = f"{EXECUTOR_HOST}/execute"

if not GOOGLE_API_KEY:
    raise ValueError("No API key found. Check your .env file.")

# Initialize the Client (New SDK)
client = genai.Client(api_key=GOOGLE_API_KEY)

pc = Pinecone(api_key=PINECONE_API_KEY)
index_name = "math-questions"
index = pc.Index(index_name)

CHAT_MODEL_NAME = "gemini-3-flash-preview"
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
    user_id: str
    session_id: Optional[str] = None 

class SaveMessageRequest(BaseModel):
    user_id: str
    session_id: str
    role: str
    content: str

class CreateSessionRequest(BaseModel):
    user_id: str
    title: Optional[str] = "New Chat"


# -------------------- Helper Functions --------------------
def send_sse_event(event_type: str, data: dict) -> str:
    """Format data as Server-Sent Event"""
    return f"event: {event_type}\ndata: {json.dumps(data)}\n\n"


# -------------------- API Endpoints --------------------

@app.post("/api/upload")
async def upload_proxy(file: UploadFile = File(...), user_id: str = Form(...)):
    """
    Receives file from React, forwards it to Docker container using Async Client.
    """
    try:
        file_content = await file.read()
        files_to_send = {'file': (file.filename, file_content, file.content_type)}
        
        # OPTIMIZATION: Use httpx for non-blocking I/O
        async with httpx.AsyncClient() as client:
            response = await client.post(f"{EXECUTOR_HOST}/upload", files=files_to_send)
        
        if response.status_code != 200:
            raise HTTPException(status_code=response.status_code, detail=f"Docker Upload Failed: {response.text}")

        return response.json()

    except httpx.RequestError: # Catch httpx specific errors
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
        
        try:
            embed_resp = ollama.embed(model=EMBEDDING_MODEL_NAME, input=query)
            query_embed = embed_resp["embeddings"][0]
        except Exception as ollama_error:
            print(f"Warning: Ollama embedding failed: {str(ollama_error)}")
            return []
        
        try:
            results = index.query(vector=query_embed, top_k=2, include_metadata=True)
        except Exception as pinecone_error:
            raise HTTPException(status_code=503, detail=f"Pinecone query failed: {str(pinecone_error)}")

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
    # 1. Input Validation
    user_query = data.user_query.strip()
    if not user_query:
        raise HTTPException(status_code=400, detail="User query is required")

    async def stream_solution():
        step_history = []
        
        # --- CONFIGURATION ---
        safety_settings = [
            types.SafetySetting(
                category=types.HarmCategory.HARM_CATEGORY_HATE_SPEECH,
                threshold=types.HarmBlockThreshold.BLOCK_NONE
            ),
            types.SafetySetting(
                category=types.HarmCategory.HARM_CATEGORY_DANGEROUS_CONTENT,
                threshold=types.HarmBlockThreshold.BLOCK_NONE
            ),
            types.SafetySetting(
                category=types.HarmCategory.HARM_CATEGORY_HARASSMENT,
                threshold=types.HarmBlockThreshold.BLOCK_NONE
            ),
            types.SafetySetting(
                category=types.HarmCategory.HARM_CATEGORY_SEXUALLY_EXPLICIT,
                threshold=types.HarmBlockThreshold.BLOCK_NONE
            ),
        ]

        config = types.GenerateContentConfig(
            temperature=0.1,
            max_output_tokens=65536,
            response_mime_type="application/json",
            safety_settings=safety_settings,
            thinking_config=types.ThinkingConfig(
                include_thoughts=False
            )
        )
        
        # 2. Initialize Chat Session
        try:
            chat_session = client.aio.chats.create(
                model=CHAT_MODEL_NAME,
                history=[],
                config=config 
            )
        except Exception as e:
            yield send_sse_event("error", {"message": f"Failed to initialize AI session: {str(e)}"})
            return

        finished = False
        code_output = "None (Start of problem)"
        max_steps = 10
        current_loop = 0
        to_do = []

        while not finished and current_loop < max_steps:
            step_number = current_loop + 1
            
            try:
                yield send_sse_event("step_start", {"step_number": step_number, "status": "generating"})

                prompt = f"""
                You are a Math Optimization Code Solver. 
                
                ROLE & STRATEGY:
                1. **SYNTAX (Copy this):** Use the REFERENCE EXAMPLES to determine which libraries to use (e.g., Pyomo vs SciPy), how to define variables, and the general code structure.
                2. **LOGIC (Derive this):** Derive the Objective Function, Constraints, and Data Values STRICTLY from the USER QUERY.
                
                CRITICAL WARNINGS:
                - **Do NOT copy constraints** from the Reference Examples unless they are explicitly stated in the User Query.
                - **Unit Check:** Analyze the units in the User Query versus the Reference. Scale inputs if necessary.
                
                CRITICAL PROTOCOL:
                1. You are NOT allowed to solve the entire problem at once.
                2. You must output EXACTLY ONE JSON object representing the immediate next step.
                3. After generating one JSON object, you must STOP immediately.
                
                GOAL: Solve this problem: "{user_query}"
                
                REFERENCE EXAMPLES:
                1. {data.problem}
                2. {data.second_problem}

                CURRENT STATUS:
                History of steps taken: {json.dumps(step_history)}
                Original to-do list: {json.dumps(to_do)}
                Output of the LAST executed code block: {code_output}

                INSTRUCTION:
                1. **Step 1 Requirement:** Your first step MUST be "Problem Analysis & Data Setup". Before writing code, explicitly PARAPHRASE the constraints you found in the *User Query*.
                2. For subsequent steps, validate the last executed step.
                3. Update the to-do list.
                4. Generate the NEXT step.
                5. Output strict JSON.
                6. After obtaining the final answer, create an extra step for the summary.
                7. FINAL STEP INSTRUCTIONS:
                   - You MUST generate one final step to present the solution.
                   - Set "is_final_step": true.
                   - Put the text summary of the answer in "description".
                   - Set "code": "" (EMPTY STRING).
                   - Keep the exact same JSON structure.
                JSON SCHEMA (Do not return a list, return a single object):
                {{
                    "step_id": integer,
                    "description": "string",
                    "code": "python code string",
                    "to_do": ["string", "string", ...],
                    "is_final_step": boolean
                }}
                """

                yield send_sse_event("ping", {"msg": "waiting_for_ai"})

                accumulated_text = ""
                try:
                    # --- FIX START ---
                    # REMOVE: response_stream = await chat_session.send_message_stream(prompt)
                    # REASON: send_message_stream IS the async generator. You cannot await it.
                    
                    # Create the stream first by AWAITING the method
                    stream = await chat_session.send_message_stream(prompt)

                    # Then iterate over the stream
                    async for chunk in stream:
                        # Verify chunk has text content before accessing
                        if chunk.text:
                            accumulated_text += chunk.text
                            yield send_sse_event("token", {"step_number": step_number, "text": chunk.text})
                            
                            # Keep this sleep! It forces the event loop to flush the buffer
                            await asyncio.sleep(0.01)
                    # --- FIX END ---
                            
                except Exception as ai_err:
                    yield send_sse_event("error", {"message": f"AI Connection Error: {str(ai_err)}"})
                    return

                # Safe JSON Parsing
                try:
                    step_data = json_repair.loads(accumulated_text)
                except Exception:
                    step_data = {"description": "Error parsing AI response", "code": "", "is_final_step": False}
                
                if not isinstance(step_data, dict):
                    step_data = {"description": f"Invalid AI Output: {str(step_data)[:100]}", "code": "", "is_final_step": False}

                to_do = step_data.get("to_do", [])
                code_to_run = step_data.get("code", "")
                
                # Execution
                yield send_sse_event("executing", {"step_number": step_number, "code": code_to_run})
                yield send_sse_event("ping", {"msg": "executing_code"}) 

                execution_result = {"output": "", "error": "", "plots": []}
                
                if code_to_run:
                    try:
                        async with httpx.AsyncClient(timeout=60.0) as exe_client:
                            resp = await exe_client.post(EXECUTOR_URL, json={"code": code_to_run})
                            if resp.status_code == 200:
                                execution_result = resp.json()
                            else:
                                execution_result = {"output": "", "error": f"Execution API Error: {resp.status_code}"}
                    except Exception as exe_err:
                        execution_result = {"output": "", "error": f"Execution Connection Failed: {str(exe_err)}"}

                code_output = execution_result.get("output", "")
                if execution_result.get("error"):
                    code_output += f"\nERROR: {execution_result['error']}"

                full_step_record = {
                    "step_id": step_data.get("step_id", step_number),
                    "description": step_data.get("description", ""),
                    "code": code_to_run,
                    "output": execution_result.get("output", ""),
                    "error": execution_result.get("error", ""),
                    "plots": execution_result.get("plots", []),
                }
                step_history.append(full_step_record)

                yield send_sse_event("step_complete", {"step": full_step_record, "step_number": step_number})

                if step_data.get("is_final_step", False):
                    finished = True
                current_loop += 1

            except Exception as loop_error:
                print(f"CRITICAL ERROR IN STEP {step_number}: {loop_error}")
                yield send_sse_event("error", {"message": f"Internal Server Error: {str(loop_error)}"})
                return

        yield send_sse_event("done", {"total_steps": len(step_history), "steps": step_history})

    return StreamingResponse(
        stream_solution(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "Connection": "keep-alive",
            "X-Accel-Buffering": "no",
        }
    )

# -------------------- FirebaseChat History Endpoints --------------------
@app.post("/api/sessions")
async def get_user_sessions(data: ChatHistoryRequest):
    """Fetch all chat session summaries for a user (Sidebar view)."""
    user_id = data.user_id.strip()
    if not user_id:
        raise HTTPException(status_code=400, detail="User ID is required")
    
    try:
        sessions = history_manager.fetch_user_sessions(user_id)
        return {"sessions": sessions, "count": len(sessions)}
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Error fetching sessions: {str(e)}")

@app.post("/api/sessions/create")
async def create_new_session(data: CreateSessionRequest):
    """Start a new chat session."""
    try:
        session_id = history_manager.create_chat_session(data.user_id, data.title)
        return {"success": True, "session_id": session_id}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))
        
@app.post("/api/chathistory")
async def get_chat_messages(data: ChatHistoryRequest):
    """Fetch all messages for a specific session."""
    user_id = data.user_id.strip()
    session_id = data.session_id
    
    if not user_id or not session_id:
        raise HTTPException(status_code=400, detail="User ID and Session ID are required")
    
    try:
        messages = history_manager.fetch_session_messages(user_id, session_id)
        return {"history": messages, "count": len(messages)}
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Error fetching messages: {str(e)}")

@app.post("/api/chathistory/save")
async def save_chat_message(data: SaveMessageRequest):
    """Save a single message (user or assistant) to a session."""
    try:
        history_manager.add_message(
            user_id=data.user_id, 
            session_id=data.session_id, 
            role=data.role, 
            content=data.content
        )
        return {"success": True}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

@app.post("/api/chathistory/clear")
async def clear_chat_history(data: ChatHistoryRequest):
    """Delete a specific session or all history."""
    user_id = data.user_id.strip()
    
    try:
        if data.session_id:
            history_manager.delete_session(user_id, data.session_id)
            message = f"Session {data.session_id} deleted"
        else:
            history_manager.clear_all_history(user_id)
            message = "All history cleared"
            
        return {"success": True, "message": message}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

