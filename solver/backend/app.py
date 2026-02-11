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
from google.genai import  types
from datetime import timedelta
from google.cloud import storage



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
isCloud = True
if isCloud:
    EXECUTOR_HOST = "https://executor-service-696616516071.us-west1.run.app"
else:
    EXECUTOR_HOST = "http://executor:8000"
EXECUTOR_URL = f"{EXECUTOR_HOST}/execute"
CHAT_MODEL_NAME = "gemini-3-flash-preview"
EMBEDDING_MODEL_NAME = "models/gemini-embedding-001"
storage_client = None 
GCS_BUCKET_NAME = os.getenv("GCS_BUCKET_NAME")
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
    session_id: Optional[str] = None 
    chat_history: Optional[List[Dict[str, Any]]] = None

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
    
class ModifyPromptRequest(BaseModel):
    user_id: str
    session_id: str
    message_index: int
    new_query: str


# -------------------- Helper Functions --------------------
def send_sse_event(event_type: str, data: dict) -> str:
    """Format data as Server-Sent Event"""
    return f"event: {event_type}\ndata: {json.dumps(data)}\n\n"

def get_storage_client():
    global storage_client
    if storage_client is None:
        try:
            # This will look for GOOGLE_APPLICATION_CREDENTIALS env var
            storage_client = storage.Client()
            logger.info("✅ GCS Storage Client initialized")
        except Exception as e:
            logger.warning(f"⚠️ GCS Storage Client failed (Local Dev?): {e}")
            return None
    return storage_client


# -------------------- API Endpoints --------------------

@app.post("/api/upload")
async def upload_proxy(
    file: UploadFile = File(...), 
    user_id: str = Form(...), 
    session_id: str = Form(...) # Add this
):
    try:
        file_content = await file.read()
        files_to_send = {'file': (file.filename, file_content, file.content_type)}
        data_to_send = {'session_id': session_id} # Change user_id to session_id
        
        async with httpx.AsyncClient() as client:
            response = await client.post(f"{EXECUTOR_HOST}/upload", files=files_to_send, data=data_to_send)
        
        if response.status_code == 413:
            raise HTTPException(status_code=413, detail="1.5GB Session Limit Exceeded")
        if response.status_code != 200:
            raise HTTPException(status_code=response.status_code, detail=f"Upload Failed: {response.text}")

        return response.json()

    except httpx.RequestError as e: # Catch httpx specific errors
        logger.error(f"Docker connection failed: {e}", extra={"tags": {"source": "backend", "endpoint": "upload"}})
        raise HTTPException(status_code=503, detail="Could not connect to Docker execution environment")
    except Exception as e:
        logger.error(f"Upload error: {e}", extra={"tags": {"source": "backend", "endpoint": "upload"}})
        print(f"Upload error: {e}")
        raise HTTPException(status_code=500, detail=str(e))

OPTIMIZATION_TAGS = [
    "Linear Programming (LP)",
    "Mixed-Integer Programming (MIP)",
    "Binary Integer Programming (BIP)",
    "Multi-period Planning",
    "Inventory & Flow Balance",
    "Blending & Quality Constraints",
    "Goal Programming (Deviation Minimization)",
    "Non-linear Programming (NLP)",
    "Combinatorial Optimization (Bin Packing)",
    "Financial & Cash Flow Modeling",
    "Vectorized Data Processing",
    "Supervised Learning (Classification)",
    "Supervised Learning (Regression)",
    "Time-Series Analysis & Rolling Statistics",
    "Survival Analysis",
    "Signal Processing (Frequency Domain)",
    "Imbalanced Class Handling",
    "Just-In-Time (JIT) Compilation",
    "Deep Learning (Neural Networks)",
    "Natural Language Processing (NLP)",
    "CAD-Integrated Optimization",
    "Geometric Containment & Rotation",
    "Data Cleaning & Preprocessing",
  ]# --- Updated app.py logic ---

async def get_references(query: str, chat_history: list):
    """
    RAG Logic: 
    1. Standalone Query: Rephrases follow-ups to avoid 'CSV' or 'export' noise.
    2. Tag Prediction: Picks method-only tags with high strictness.
    3. Pinecone Search: Uses tags as a soft pre-filter with a vector-only fallback.
    """
    try:
        search_query = query
    

        # --- 2. PREDICT RELEVANT TAGS (Strict Prompting) ---
        predicted_tags = []
        tag_prompt = f"""
        Identify which math or data analysis categories the final query relates to. Only choose categories from the allowed list of tags. If none fit, don't choose any. Focus on the last query. 
        
        ALLOWED TAGS: {json.dumps(OPTIMIZATION_TAGS)}
        QUERY: "{search_query}"
        
        Return ONLY a JSON list of strings. If none apply, return []."""
        
        try:
            tag_resp = genai_client.models.generate_content(
                model=CHAT_MODEL_NAME,
                contents=tag_prompt,
                config=types.GenerateContentConfig(response_mime_type="application/json", temperature=0.0)
            )
            predicted_tags = json_repair.loads(tag_resp.text)
            # Filter out any hallucinations not in our master list
            predicted_tags = [t for t in predicted_tags if t in OPTIMIZATION_TAGS]
            logger.info(f"🏷️ Predicted Tags: {predicted_tags}")
        except Exception as e:
            logger.error(f"Tag prediction failed: {e}")

        # --- 3. EMBEDDING ---
        embed_resp = genai_client.models.embed_content(
            model=EMBEDDING_MODEL_NAME,
            contents=search_query,
            config=types.EmbedContentConfig(task_type='RETRIEVAL_QUERY')
        )
        query_embed = embed_resp.embeddings[0].values

        # --- 4. FUZZY TAG SEARCH ---
        # We use $in which acts as an 'OR' match. This matches any document 
        # that has at least ONE of the predicted tags.
        pinecone_filter = {
                "$or": [
                    {"tags": {"$in": predicted_tags}},
                    {"tag": {"$in": predicted_tags}}
                ]
            } if predicted_tags else None
        
        results = index.query(
            vector=query_embed, 
            top_k=2, 
            include_metadata=True, 
            filter=pinecone_filter
        )
        
        # Robust Fallback: If tags were too specific or wrong, drop them and rely on Vector Similarity
        if not results.get("matches") or len(results["matches"]) == 0:
            logger.info("⚠️ No matches found with tags. Falling back to vector-only search.")
            results = index.query(vector=query_embed, top_k=2, include_metadata=True)
        
        # --- 5. FORMAT RESULTS ---
        refs = []
        for match in results.get("matches", []):
            try:
                # Assuming your metadata is stored in a 'json' field
                meta_json = match.get("metadata", {}).get("json")
                if meta_json:
                    meta = json.loads(meta_json)
                    refs.append(format_reference(meta))
            except: continue
            
        while len(refs) < 2:
            refs.append("Reference example not found.")
            
        return refs[0], refs[1]

    except Exception as e:
        logger.error(f"CRITICAL RAG ERROR: {e}")
        return "Reference unavailable.", "Reference unavailable."

def format_reference(data):
    """Formats the JSON metadata into the string Gemini expects."""
    if not data: return ""
    return f"PROBLEM: {data.get('problem')}\nSTEPS: {json.dumps(data.get('steps'))}"

@app.post("/api/prompt/modify")
async def modify_prompt(data: ModifyPromptRequest):
    try:
        history_manager.truncate_session(data.user_id, data.session_id, data.message_index)
        async with httpx.AsyncClient() as client:
            await client.delete(f"{EXECUTOR_HOST}/cleanup/{data.session_id}")
        
        return {"success": True}  # Change 'true' to 'True'
    except Exception as e:
        logger.error(f"Modify Prompt Error: {e}")
        raise HTTPException(status_code=500, detail=str(e))

@app.post("/api/solve")
async def solve(data: SolveRequest):
    user_query = data.user_query.strip()
    if not user_query:
        raise HTTPException(status_code=400, detail="User query is required")

    async def stream_solution():
        
        ref1, ref2 = await get_references(user_query, data.chat_history or [])

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

                chat_context = ""
                if data.chat_history:
                    try:
                        formatted_msgs = []
                        for m in data.chat_history[-10:]:
                            role = m.get('role', '').upper()
                            content = m.get('content', '')
                            formatted_msgs.append(f"{role}: {content}")
                        
                        formatted_history = "\n".join(formatted_msgs)
                        chat_context = f"PREVIOUS CONVERSATION HISTORY:\n{formatted_history}\n"
                    except Exception as e:
                        logger.error(f"Failed to process provided chat_history: {e}")

                elif data.user_id and data.session_id:
                    try:
                        history_msgs = history_manager.fetch_session_messages(data.user_id, data.session_id)
                        if history_msgs:
                            formatted_msgs = []
                            for m in history_msgs[-10:]:
                                role = m['role'].upper()
                                content = m['content']
                                if m['role'] == 'assistant':
                                    try:
                                        clean_content = content.strip()
                                        if clean_content.startswith('{') or clean_content.startswith('['):
                                            data_obj = json.loads(clean_content)
                                            if isinstance(data_obj, dict) and 'steps' in data_obj:
                                                steps_desc = []
                                                for s in data_obj['steps']:
                                                    desc = s.get('description', '')
                                                    code = s.get('code', '')
                                                    steps_desc.append(f"- {desc}\nCode:\n{code}")
                                                content = "Solution Steps:\n" + "\n".join(steps_desc)
                                    except:
                                        pass # Keep original content if parse fails
                                formatted_msgs.append(f"{role}: {content}")
                            
                            formatted_history = "\n".join(formatted_msgs)
                            chat_context = f"PREVIOUS CONVERSATION HISTORY:\n{formatted_history}\n"
                    except Exception as e:
                        logger.error(f"Failed to load history for prompt: {e}")

                prompt = f"""
                You are a Math Optimization Code Solver. 
                
                {chat_context}

                ROLE & STRATEGY:
                1. **SYNTAX (Copy this):** Use the REFERENCE EXAMPLES to determine which libraries to use (e.g., Pyomo vs SciPy), how to define variables, and the general code structure.
                2. **LOGIC (Derive this):** Derive the Objective Function, Constraints, and Data Values STRICTLY from the USER QUERY.
                3. Core Philosophy: Optimization problems (MIP/LP) are computationally expensive. You prioritize PRACTICAL execution over theoretical perfection. Your code must run within strict time limits and handle infeasibility gracefully.

                CRITICAL WARNINGS:
                - **Do NOT copy constraints** from the Reference Examples unless they are explicitly stated in the User Query.
                - **Unit Check:** Analyze the units in the User Query versus the Reference. Scale inputs if necessary.
                - **SOLVER SAFETY (MANDATORY):** Every solver call MUST have a time limit (e.g., `solver.options['time_limit'] = 30`). You must check `results.solver.termination_condition` for `maxTimeLimit` and handle it without crashing.
                - **EFFICIENCY:** Avoid 3-index variables (e.g., x[i,j,k]) for Routing problems if a 2-index formulation (x[i,j]) suffices.
                - **UPLOAD ACCESS** Uploaded files are stored in `/app/uploads/` in the Docker container, use "uploads/upload_name.txt".

                CRITICAL: ENVIRONMENT CONSTRAINTS
                - RAM Limit: 1,000 MB (1GB). Large files will cause Out-Of-Memory (OOM) errors.
                - Execution Limit: 60 seconds.
                MANDATORY MEMORY-EFFICIENT STRATEGIES:
                - Initial Inspection: Always read the first 5-10 rows first (nrows=10) to identify column names and the "messy" data formats (e.g., currency symbols, null placeholders).
                - Column Pruning: Never load the full dataset. Use the usecols parameter in pd.read_csv or pd.read_excel to load only the specific columns required for the math.
                - Chunking: For files > 50MB, use chunksize to process data in blocks of 10,000 rows, performing aggregations (like .sum() or .count()) per chunk.
                - Downcasting: Cast numeric data to smaller types immediately (e.g., float32 instead of float64) using pd.to_numeric().
                - Avoid Excel Engines: If a CSV version of a dataset is available, use it. If you must use Excel, use engine='openpyxl' but limit nrows strictly to 50,000.
                
                CRITICAL PROTOCOL:
                1. **COMPLEX PROBLEMS:** YOU MUST DECOMPOSE into steps. Do NOT solve at once.
                2. **TRIVIAL PROBLEMS** (e.g. simple graphing, sorting, basic arithmetic): You MAY solve in a single step but don't set as final step parameter because errors may arise.
                3. Do not set is final step to true until the code output succeeds
                
                DIRECTORY & FILE ACCESS:
                - Your working directory is the root of the current session.
                - **READING UPLOADS:** User-uploaded files are located in the "uploads/" folder. Use: `pd.read_csv("uploads/filename.csv")`.
                - **SAVING EXPORTS:** To provide a file for the user to download, you MUST save it to the "exports/" folder. Use: `df.to_csv("exports/results.csv")`.
                - **PLOTS:** Standard `matplotlib` or `plotly` displays will be captured automatically; you do not need to save them to "exports/" unless the user specifically asks for an image file.
                - **GCS UPLOADS:** Any file saved to "exports/" will be automatically uploaded to Google Cloud Storage for user download.

                GOAL: Solve this problem: "{user_query}"

                REFERENCE EXAMPLES:
                1. {ref1}
                2. {ref2}

                CURRENT STATUS:
                History of steps taken: {json.dumps(step_history)}
                Original to-do list: {json.dumps(to_do)}
                Output of the LAST executed code block: {code_output}

                INSTRUCTION:
                1. **Step 1 Requirement:**
                   - **IF COMPLEX:** First step MUST be "Problem Analysis, Feasibility Check & Data Setup". Explicitly PARAPHRASE constraints and perform "Napkin Math" (e.g. Total Demand vs Total Capacity) to check for obvious infeasibility before coding.
                   - **IF TRIVIAL:** You may skip analysis and proceed directly to generating the solution code.
                2. For subsequent steps, validate the last executed step.
                3. Update the to-do list.
                4. Generate the NEXT numbered step
                5. If the previous step failed, redo the step BUT STILL ITERATE THE STEP NUMBER.
                6. Output strict JSON.
                7. After obtaining the final answer, create an extra step for the summary.
                8. FINAL STEP INSTRUCTIONS:
                   - Typically, create a dedicated final step with "code": "" to summarize.
                   - **EXCEPTION FOR TRIVIAL PROBLEMS:** You may set "is_final_step": true in the SAME step where you write the code, effectively solving and summarizing in one step.
                   - Otherwise, set "is_final_step": true, put text summary in "description", and set "code": "".
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
                        # SAFETY CHECK: Ensure session_id is a string, never None
                        clean_session_id = data.session_id or "fallback_session"
                        
                        async with httpx.AsyncClient(timeout=60.0) as exe_client:
                            resp = await exe_client.post(EXECUTOR_URL, json={
                                "code": code_to_run,
                                "session_id": clean_session_id, # Use cleaned ID
                                "timeout": 60
                            })
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
                    
                final_files = []
                if execution_result.get("files"):
                    for file_info in execution_result["files"]:
                        signed_url = generate_signed_download_url(file_info["gcs_path"])
                        if signed_url:
                            final_files.append({
                                "name": file_info["name"],
                                "download_url": signed_url
                            })

                full_step_record = {
                    "step_id": step_data.get("step_id", step_number),
                    "description": step_data.get("description", ""),
                    "code": code_to_run,
                    "output": execution_result.get("output", ""),
                    "error": execution_result.get("error", ""),
                    "plots": execution_result.get("plots", []),
                    "files": final_files,
                }
                step_history.append(full_step_record)

                yield send_sse_event("step_complete", {"step": full_step_record, "step_number": step_number})

                if step_data.get("is_final_step", False):
                    if execution_result.get("error"):
                         logger.warning(f"Step marked final but failed with error: {execution_result['error']}. Continuing loop.")
                         finished = False
                    else:
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
    user_id = data.user_id.strip()
    try:
        if data.session_id:
            history_manager.delete_session(user_id, data.session_id)
            async with httpx.AsyncClient() as client:
                await client.delete(f"{EXECUTOR_HOST}/cleanup/{data.session_id}")
            message = f"Session {data.session_id} deleted."
        else:
            history_manager.clear_all_history(user_id)
            message = "All history cleared."
            
        return {"success": True, "message": message}
    except Exception as e:
        logger.error(f"Clear History Error: {e}")
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

@app.post("/api/session/close")
async def close_session(data: ChatHistoryRequest):
    """
    Called when a user closes their tab. 
    Wipes the executor files but KEEPS Firebase history.
    """
    if data.session_id:
        try:
            async with httpx.AsyncClient() as client:
                # Trigger the executor's cleanup only
                await client.delete(f"{EXECUTOR_HOST}/cleanup/{data.session_id}")
            return {"status": "success", "message": "Executor disk space reclaimed."}
        except Exception as e:
            logger.error(f"Silent cleanup failed: {e}")
            return {"status": "error", "message": str(e)}
    return {"status": "noop"}
    
def generate_signed_download_url(gcs_path: str):
    if gcs_path == "local_test_mode" or not GCS_BUCKET_NAME:
        return "#local-test-no-gcs-link"
    client = get_storage_client()
    if not client:
        return None # Gracefully fail if not authenticated
        
    try:
        bucket = client.bucket(GCS_BUCKET_NAME)
        blob = bucket.blob(gcs_path)
        return blob.generate_signed_url(
            version="v4",
            expiration=timedelta(minutes=60),
            method="GET"
        )
    except Exception as e:
        logger.error(f"Failed to sign URL: {e}")
        return None
STORAGE_LIMIT_BYTES = 1.5 * 1024 * 1024 * 1024  # 1.5 GB

def get_user_storage_usage(user_id: str):
    """Calculates total bytes used by a user in GCS."""
    client = get_storage_client()
    if not client or not GCS_BUCKET_NAME:
        return 0
    
    try:
        bucket = client.bucket(GCS_BUCKET_NAME)
        # Assuming files are stored as 'outputs/{user_id}/...' or 'uploads/{user_id}/...'
        # We check all files belonging to this user
        blobs = bucket.list_blobs(prefix=f"user_data/{user_id}/")
        total_size = sum(blob.size for blob in blobs if blob.size)
        return total_size
    except Exception as e:
        logger.error(f"Error checking storage usage: {e}")
        return 0

