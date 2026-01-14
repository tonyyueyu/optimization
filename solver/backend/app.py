import os
import json
import httpx 
_original_async_client_init = httpx.AsyncClient.__init__

def _patched_async_client_init(self, *args, **kwargs):
    kwargs['timeout'] = httpx.Timeout(600.0, connect=60.0, read=600.0, write=60.0, pool=60.0)
    return _original_async_client_init(self, *args, **kwargs)

httpx.AsyncClient.__init__ = _patched_async_client_init
print("✅ HTTPX patched with 600s timeout")

import asyncio
import logging
import logging_loki
import json_repair
import ollama
from dotenv import load_dotenv
from fastapi import FastAPI, HTTPException, UploadFile, File, Form
from fastapi.middleware.cors import CORSMiddleware 
from fastapi.responses import StreamingResponse
from pydantic import BaseModel
from typing import Optional, List, Dict, Any
from pinecone import Pinecone
from history_manager import HistoryManager

# --- NEW SDK IMPORTS (Correct for Gemini 3) ---
from google import genai
from google.genai import types
# -----------------------

# -- CONFIGURATION --
load_dotenv()


# --- LOKI LOGGING SETUP ---
LOKI_URL = os.getenv("LOKI_URL", "http://localhost:3100/loki/api/v1/push")
LOKI_USERNAME = os.getenv("LOKI_USERNAME")
LOKI_PASSWORD = os.getenv("LOKI_PASSWORD")

loki_auth = None
if LOKI_USERNAME and LOKI_PASSWORD:
    loki_auth = (LOKI_USERNAME, LOKI_PASSWORD)

try:
    handler = logging_loki.LokiHandler(
        url=LOKI_URL, 
        tags={"application": "fastapi-backend"},
        auth=loki_auth,
        version="1",
    )
    logger = logging.getLogger("backend-logger")
    logger.setLevel(logging.ERROR)
    logger.addHandler(handler)
except Exception as e:
    print(f"Failed to initialize Loki logging: {e}")
    logger = logging.getLogger("backend-logger")
    logger.setLevel(logging.ERROR)

# Add console handler so we see logs in terminal too
console_handler = logging.StreamHandler()
console_handler.setLevel(logging.INFO)
logger.addHandler(console_handler)
# ---------------------------

GOOGLE_API_KEY = os.getenv("GOOGLE_API_KEY")
PINECONE_API_KEY = os.getenv("PINECONE_API_KEY")

# Split URL to easily access base and execute endpoints
EXECUTOR_HOST = "http://localhost:8000"
EXECUTOR_URL = f"{EXECUTOR_HOST}/execute"

if not GOOGLE_API_KEY:
    raise ValueError("No API key found. Check your .env file.")


pc = Pinecone(api_key=PINECONE_API_KEY)
index_name = "math-questions"
index = pc.Index(index_name)

# RESTORED: User confirmed this was working
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

class LogErrorRequest(BaseModel):
    source: str # "frontend" or "backend"
    message: str
    stack_trace: Optional[str] = None
    user_id: Optional[str] = None
    additional_data: Optional[Dict[str, Any]] = None


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

    except httpx.RequestError as e: # Catch httpx specific errors
        logger.error(f"Docker connection failed: {e}", extra={"tags": {"source": "backend", "endpoint": "upload"}})
        raise HTTPException(status_code=503, detail="Could not connect to Docker execution environment")
    except Exception as e:
        logger.error(f"Upload error: {e}", extra={"tags": {"source": "backend", "endpoint": "upload"}})
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
            logger.warning(f"Ollama embedding failed: {str(ollama_error)}", extra={"tags": {"source": "backend"}})
            print(f"Warning: Ollama embedding failed: {str(ollama_error)}")
            return []
        
        try:
            results = index.query(vector=query_embed, top_k=2, include_metadata=True)
        except Exception as pinecone_error:
            logger.error(f"Pinecone query failed: {pinecone_error}", extra={"tags": {"source": "backend"}})
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
        logger.error(error_msg, extra={"tags": {"source": "backend", "endpoint": "retrieve"}})
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
            response_mime_type="application/json",
            thinking_config=types.ThinkingConfig(
               include_thoughts=False
            )
        )
        
        try:
            http_opts = types.HttpOptions(
                timeout=60000,  # Try seconds first
                # api_version='v1beta'  # Uncomment if needed
            )
            local_client = genai.Client(
                api_key=GOOGLE_API_KEY,
                http_options=http_opts
            )
            print(f"DEBUG: Client type: {type(local_client)}")
            if hasattr(local_client, '_api_client'):
                api_client = local_client._api_client
                print(f"DEBUG: API Client attrs: {[x for x in dir(api_client) if not x.startswith('__')]}")
                
                # Check for httpx clients
                for attr in ['_httpx_client', '_async_httpx_client', 'async_client', '_client', 'httpx_client', '_http_client']:
                    if hasattr(api_client, attr):
                        client_obj = getattr(api_client, attr)
                        print(f"DEBUG: Found {attr}: {client_obj}")
                        if hasattr(client_obj, 'timeout'):
                            print(f"DEBUG: {attr}.timeout = {client_obj.timeout}")
            
            chat_session = local_client.aio.chats.create(
                    model=CHAT_MODEL_NAME,
                    history=[],
                    config=config 
                )
        except Exception as e:
            logger.error(f"Failed to initialize AI: {e}", extra={"tags": {"source": "backend", "endpoint": "solve"}})
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
                3. Core Philosophy: Optimization problems (MIP/LP) are computationally expensive. You prioritize PRACTICAL execution over theoretical perfection. Your code must run within strict time limits and handle infeasibility gracefully.

                CRITICAL WARNINGS:
                - **Do NOT copy constraints** from the Reference Examples unless they are explicitly stated in the User Query.
                - **Unit Check:** Analyze the units in the User Query versus the Reference. Scale inputs if necessary.
                - **SOLVER SAFETY (MANDATORY):** Every solver call MUST have a time limit (e.g., `solver.options['time_limit'] = 30`). You must check `results.solver.termination_condition` for `maxTimeLimit` and handle it without crashing.
                - **EFFICIENCY:** Avoid 3-index variables (e.g., x[i,j,k]) for Routing problems if a 2-index formulation (x[i,j]) suffices.

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
                1. **Step 1 Requirement:** Your first step MUST be "Problem Analysis, Feasibility Check & Data Setup". Explicitly PARAPHRASE constraints and perform "Napkin Math" (e.g. Total Demand vs Total Capacity) to check for obvious infeasibility before coding.
                2. For subsequent steps, validate the last executed step.
                3. Update the to-do list.
                4. Generate the NEXT numbered step
                5. If the previous step failed, redo the step BUT STILL ITERATE THE STEP NUMBER.
                6. Output strict JSON.
                7. After obtaining the final answer, create an extra step for the summary.
                8. FINAL STEP INSTRUCTIONS:
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
                    print(f"DEBUG: Calling Gemini Stream (Timeout=600s)...")
                    stream_response = await chat_session.send_message_stream(prompt)
                    
                    async for chunk in stream_response:
                        if chunk.text:
                            accumulated_text += chunk.text
                            yield send_sse_event("token", {"step_number": step_number, "text": chunk.text})
                            await asyncio.sleep(0.01) # Keep UI responsive
                except Exception as ai_err:
                    logger.error(f"AI Error: {ai_err}")
                    print(f"\nCRITICAL AI ERROR: {type(ai_err).__name__}")
                    print(f"Details: {str(ai_err)}")
                    
                    # PRINT FULL TRACEBACK to see exactly where it fails
                    import traceback
                    traceback.print_exc()
                    print(f"\nCRITICAL AI ERROR: {type(ai_err).__name__}")
                    print(f"Details: {str(ai_err)}") 
                    
                    yield send_sse_event("error", {"message": f"AI Error: {str(ai_err)}"})
                    return

                # Safe JSON Parsing
                try:
                    step_data = json_repair.loads(accumulated_text)
                except Exception as e:
                    logger.error(f"JSON Parse Error: {e}\nPayload: {accumulated_text}", extra={"tags": {"source": "backend"}})
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
                        logger.error(f"Executor Connection Error: {exe_err}", extra={"tags": {"source": "backend"}})
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
                logger.error(f"Critical Loop Error: {loop_error}", extra={"tags": {"source": "backend", "step": step_number}})
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
        logger.error(f"Fetch Sessions Error: {e}", extra={"tags": {"source": "backend"}})
        raise HTTPException(status_code=500, detail=f"Error fetching sessions: {str(e)}")

@app.post("/api/sessions/create")
async def create_new_session(data: CreateSessionRequest):
    """Start a new chat session."""
    try:
        session_id = history_manager.create_chat_session(data.user_id, data.title)
        return {"success": True, "session_id": session_id}
    except Exception as e:
        logger.error(f"Create Session Error: {e}", extra={"tags": {"source": "backend"}})
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
        logger.error(f"Fetch History Error: {e}", extra={"tags": {"source": "backend"}})
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
        logger.error(f"Save Message Error: {e}", extra={"tags": {"source": "backend"}})
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
        logger.error(f"Clear History Error: {e}", extra={"tags": {"source": "backend"}})
        raise HTTPException(status_code=500, detail=str(e))

@app.post("/api/log_error")
async def log_error(data: LogErrorRequest):
    """Log an error to Loki."""
    try:
        logger.error(
            data.message, 
            extra={
                "tags": {"source": data.source, "user_id": data.user_id or "anonymous"},
                "stack_trace": data.stack_trace,
                "additional_data": str(data.additional_data)
            }
        )
        return {"status": "logged"}
    except Exception as e:
        print(f"Failed to log error to Loki: {e}")
        # Don't fail the request if logging fails, just print to stdout
        return {"status": "failed_to_log", "error": str(e)}