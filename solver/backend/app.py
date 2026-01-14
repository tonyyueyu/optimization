import os
import json
import httpx
import asyncio
import logging
import json_repair
from dotenv import load_dotenv
from fastapi import FastAPI, HTTPException, UploadFile, File, Form
from fastapi.middleware.cors import CORSMiddleware 
from fastapi.responses import StreamingResponse
from pydantic import BaseModel
from typing import Optional, List, Dict, Any
from pinecone import Pinecone
from history_manager import HistoryManager
import google.cloud.logging
from google.cloud.logging.handlers import CloudLoggingHandler
from google import genai
from google.genai import types

# 1. Patch HTTPX (Keep this at the very top)
_original_async_client_init = httpx.AsyncClient.__init__
def _patched_async_client_init(self, *args, **kwargs):
    kwargs['timeout'] = httpx.Timeout(600.0, connect=60.0, read=600.0, write=60.0, pool=60.0)
    return _original_async_client_init(self, *args, **kwargs)
httpx.AsyncClient.__init__ = _patched_async_client_init

# 2. Environment & Logging
load_dotenv()

def setup_logger():
    l = logging.getLogger("backend-logger")
    l.setLevel(logging.INFO)
    # Only attach Cloud Logging if running in the cloud
    if os.getenv("K_SERVICE"): 
        try:
            client = google.cloud.logging.Client()
            client.setup_logging()
        except Exception as e:
            print(f"Cloud Logging failed to init: {e}")
    
    if not l.handlers:
        handler = logging.StreamHandler()
        l.addHandler(handler)
    return l

logger = setup_logger()

# 3. Safe Global State
GOOGLE_API_KEY = os.getenv("GOOGLE_API_KEY")
PINECONE_API_KEY = os.getenv("PINECONE_API_KEY")
EXECUTOR_HOST = "https://executor-service-696616516071.us-west1.run.app"
EXECUTOR_URL = f"{EXECUTOR_HOST}/execute"
CHAT_MODEL_NAME = "gemini-3-flash-preview"
EMBEDDING_MODEL_NAME = "text-embedding-004"

# GLOBAL CLIENTS
genai_client = None
index = None
history_manager = HistoryManager() # Initialize history manager here

if not GOOGLE_API_KEY:
    logger.error("❌ GOOGLE_API_KEY is not set!")
else:
    logger.info(f"✅ GOOGLE_API_KEY loaded (...{GOOGLE_API_KEY[-4:]})")
    genai_client = genai.Client(api_key=GOOGLE_API_KEY)

if not PINECONE_API_KEY:
    logger.error("❌ PINECONE_API_KEY is not set!")
else:
    logger.info(f"✅ PINECONE_API_KEY loaded (...{PINECONE_API_KEY[-4:]})")
    try:
        pc = Pinecone(api_key=PINECONE_API_KEY)
        index = pc.Index("math-questions") # Ensure your index name is correct
    except Exception as e:
        logger.error(f"❌ Pinecone Init Failed: {e}")
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
        try:
            embed_resp = genai_client.models.embed_content(
                model=EMBEDDING_MODEL_NAME,
                contents=query,
                config=types.EmbedContentConfig(
                    task_type='RETRIEVAL_QUERY'
                )
            )
            query_embed = embed_resp.embeddings[0].values
            
        except Exception as gemini_error:
            logger.error(f"Gemini embedding failed: {str(gemini_error)}", extra={"tags": {"source": "backend"}})
            return []
        
        try:
            results = index.query(vector=query_embed, top_k=2, include_metadata=True)
        except Exception as pinecone_error:
            logger.error(f"Pinecone query failed: {pinecone_error}", extra={"tags": {"source": "backend"}})
            raise HTTPException(status_code=503, detail="Search index unavailable")

        res = []
        for match in results.get("matches", []):
            metadata_json = match.get("metadata", {}).get("json")
            if metadata_json:
                try:
                    obj = json.loads(metadata_json)
                    res.append({
                        "score": match["score"],
                        "id": obj.get("id"),
                        "problem": obj.get("problem"),
                        "solution": obj.get("solution"),
                        "steps": obj.get("steps"),
                    })
                except json.JSONDecodeError:
                    continue
        return res 

    except Exception as e:
        logger.error(f"Retrieval failed: {str(e)}", extra={"tags": {"source": "backend"}})
        raise HTTPException(status_code=500, detail="Internal server error during retrieval")

@app.post("/api/solve")
async def solve(data: SolveRequest):
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
    """Log an error to Google Cloud Logging."""
    try:
        log_data = {
            "labels": {
                "source": data.source,
                "user_id": data.user_id or "anonymous"
            },
            "stack_trace": data.stack_trace,
            "additional_data": data.additional_data
        }

        logger.error(data.message, extra=log_data)
        
        return {"status": "logged"}
    except Exception as e:
        print(f"Failed to log error to Google Cloud: {e}")
        return {"status": "failed_to_log", "error": str(e)}