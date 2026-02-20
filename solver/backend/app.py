import os
import json
import httpx
import asyncio
import logging
import traceback
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
from datetime import timedelta
from google.cloud import storage


_original_async_client_init = httpx.AsyncClient.__init__
def _patched_async_client_init(self, *args, **kwargs):
    kwargs['timeout'] = httpx.Timeout(600.0, connect=60.0, read=600.0, write=60.0, pool=60.0)
    return _original_async_client_init(self, *args, **kwargs)
httpx.AsyncClient.__init__ = _patched_async_client_init

load_dotenv()

def setup_logger():
    """
    Sets up the application logger, including Google Cloud Logging 
    if running in a deployed environment (K_SERVICE).
    """
    l = logging.getLogger("backend-logger")
    l.setLevel(logging.INFO)
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

GOOGLE_API_KEY = os.getenv("GOOGLE_API_KEY")
PINECONE_API_KEY = os.getenv("PINECONE_API_KEY")
STORAGE_LIMIT_BYTES = 1.5 * 1024 * 1024 * 1024  # 1.5 GB

isCloud = True
if isCloud:
    # EXECUTOR_HOST = "https://executor-service-696616516071.us-west1.run.app"
    EXECUTOR_HOST = "https://executor-service-test-696616516071.us-west1.run.app"
else:
    EXECUTOR_HOST = "http://executor:8000"
EXECUTOR_URL = f"{EXECUTOR_HOST}/execute"
CHAT_MODEL_NAME = "gemini-3-flash-preview"
EMBEDDING_MODEL_NAME = "models/gemini-embedding-001"
storage_client = None
GCS_BUCKET_NAME = os.getenv("GCS_BUCKET_NAME")

genai_client = None
index = None
history_manager = HistoryManager()

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
        index = pc.Index("math-questions")
    except Exception as e:
        logger.error(f"❌ Pinecone Init Failed: {e}")

app = FastAPI()

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["GET", "POST", "PUT", "DELETE", "OPTIONS", "PATCH"],
    allow_headers=["*"],
    expose_headers=["*"],
)


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
    source: str
    message: str
    stack_trace: Optional[str] = None
    user_id: Optional[str] = None
    additional_data: Optional[Dict[str, Any]] = None

class ModifyPromptRequest(BaseModel):
    user_id: str
    session_id: str
    message_index: int
    new_query: str


def send_sse_event(event_type: str, data: dict) -> str:
    return f"event: {event_type}\ndata: {json.dumps(data)}\n\n"

def get_storage_client():
    global storage_client
    if storage_client is None:
        try:
            storage_client = storage.Client()
            logger.info("✅ GCS Storage Client initialized")
        except Exception as e:
            logger.warning(f"⚠️ GCS Storage Client failed (Local Dev?): {e}")
            return None
    return storage_client

def generate_signed_download_url(gcs_path: str):
    if gcs_path == "local_test_mode" or not GCS_BUCKET_NAME:
        return "#local-test-no-gcs-link"
    client = get_storage_client()
    if not client:
        return None
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

def get_user_storage_usage(user_id: str):
    client = get_storage_client()
    if not client or not GCS_BUCKET_NAME:
        return 0
    try:
        bucket = client.bucket(GCS_BUCKET_NAME)
        blobs = bucket.list_blobs(prefix=f"user_data/{user_id}/")
        total_size = sum(blob.size for blob in blobs if blob.size)
        return total_size
    except Exception as e:
        logger.error(f"Error checking storage usage: {e}")
        return 0


@app.post("/api/upload")
async def upload_proxy(
    file: UploadFile = File(...),
    user_id: str = Form(...),
    session_id: str = Form(...)
):
    """Upload directly to GCS — no executor dependency."""
    try:
        client = get_storage_client()
        if not client:
            raise HTTPException(status_code=503, detail="GCS not available")

        file_content = await file.read()

        bucket = client.bucket(GCS_BUCKET_NAME)
        prefix = f"uploads/{session_id}/"
        current_usage = sum(
            b.size for b in bucket.list_blobs(prefix=prefix) if b.size
        )
        if current_usage + len(file_content) > STORAGE_LIMIT_BYTES:
            raise HTTPException(status_code=413, detail="1.5GB session limit exceeded")

        blob = bucket.blob(f"uploads/{session_id}/{file.filename}")
        blob.upload_from_string(file_content, content_type=file.content_type)

        return {
            "status": "success",
            "filename": file.filename,
            "path": f"uploads/{file.filename}"
        }
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Upload error: {e}")
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
    "Large File Chunking",
]


async def get_references(query: str, chat_history: list):
    """
    Retrieves reference examples from Pinecone based on the user's query.
    Extracts tags using a lightweight LLM call to filter relevant math/optimization categories.
    """
    try:
        search_query = query

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
            predicted_tags = [t for t in predicted_tags if t in OPTIMIZATION_TAGS]
            logger.info(f"🏷️ Predicted Tags: {predicted_tags}")
        except Exception as e:
            logger.error(f"Tag prediction failed: {e}")

        embed_resp = genai_client.models.embed_content(
            model=EMBEDDING_MODEL_NAME,
            contents=search_query,
            config=types.EmbedContentConfig(task_type='RETRIEVAL_QUERY')
        )
        query_embed = embed_resp.embeddings[0].values

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

        if not results.get("matches") or len(results["matches"]) == 0:
            logger.info("⚠️ No matches found with tags. Falling back to vector-only search.")
            results = index.query(vector=query_embed, top_k=2, include_metadata=True)

        refs = []
        for match in results.get("matches", []):
            try:
                meta_json = match.get("metadata", {}).get("json")
                if meta_json:
                    meta = json.loads(meta_json)
                    refs.append(format_reference(meta))
            except:
                continue

        while len(refs) < 2:
            refs.append("Reference example not found.")

        return refs[0], refs[1]

    except Exception as e:
        logger.error(f"CRITICAL RAG ERROR: {e}")
        return "Reference unavailable.", "Reference unavailable."


def format_reference(data):
    """Formats the retrieved reference data into a structured prompt string."""
    if not data:
        return ""
    return f"PROBLEM: {data.get('problem')}\nSTEPS: {json.dumps(data.get('steps'))}"


@app.post("/api/prompt/modify")
async def modify_prompt(data: ModifyPromptRequest):
    try:
        history_manager.truncate_session(data.user_id, data.session_id, data.message_index)
        async with httpx.AsyncClient() as client:
            await client.delete(f"{EXECUTOR_HOST}/cleanup/{data.session_id}")
        return {"success": True}
    except Exception as e:
        logger.error(f"Modify Prompt Error: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@app.post("/api/solve")
async def solve(data: SolveRequest):
    """
    Main endpoint for solving optimization/math problems.
    Generates steps using Gemini, executes them in a remote kernel (executor),
    and streams back the execution updates and final results via SSE.
    """
    user_query = data.user_query.strip()
    if not user_query:
        raise HTTPException(status_code=400, detail="User query is required")

    async def stream_solution():

        ref1, ref2 = await get_references(user_query, data.chat_history or [])

        step_history = []

        # Persistent HTTP client — keeps Cloud Run session affinity cookie
        # so all steps within one solve hit the same executor instance.
        executor_client = httpx.AsyncClient(
            timeout=httpx.Timeout(180.0, connect=30.0)
        )

        try:
            config = types.GenerateContentConfig(
                temperature=0.1,
                response_mime_type="application/json",
                thinking_config=types.ThinkingConfig(
                    include_thoughts=False
                )
            )

            try:
                http_opts = types.HttpOptions(timeout=60000)
                local_client = genai.Client(
                    api_key=GOOGLE_API_KEY,
                    http_options=http_opts
                )

                chat_session = local_client.aio.chats.create(
                    model=CHAT_MODEL_NAME,
                    history=[],
                    config=config
                )
            except Exception as e:
                logger.error(f"Failed to initialize AI: {e}")
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
                                            pass
                                    formatted_msgs.append(f"{role}: {content}")
                                formatted_history = "\n".join(formatted_msgs)
                                chat_context = f"PREVIOUS CONVERSATION HISTORY:\n{formatted_history}\n"
                        except Exception as e:
                            logger.error(f"Failed to load history for prompt: {e}")

                    prompt = f"""
                        You are a Math Optimization Code Solver.

                        {chat_context}

                        ROLE:
                        - **SYNTAX:** Mirror the REFERENCE EXAMPLES for library choice, variable definitions, and code structure.
                        - **LOGIC:** Derive objectives, constraints, and data STRICTLY from the USER QUERY. Do NOT copy constraints from references.
                        - **Unit Check:** Scale inputs if units differ between query and references.

                        SOLVER HIERARCHY (MANDATORY):
                        Use the strongest available solver. Do NOT default to scipy/scikit-learn when industrial solvers apply:
                        1. **MIP/LP/MILP:** Pyomo + Gurobi (preferred) or GLPK. Set `solver.options['TimeLimit'] = 30`.
                        2. **Nonlinear/NLP:** Pyomo + IPOPT.
                        3. **ML/Prediction:** XGBoost (preferred over scikit-learn for tabular data).
                        4. **scipy.optimize / scikit-learn:** ONLY for simple curve fitting, root finding, or when no structured optimization is needed.
                        Every solver call MUST have a time limit and check termination conditions (e.g., `maxTimeLimit`) gracefully.

                        PACKAGE INSTALLATION:
                        - You may `pip install` lightweight packages (e.g., `pyomo`, `xgboost`, `plotly`).
                        - Do NOT attempt to install large packages requiring system dependencies or conda (e.g., `tensorflow`, `pytorch`, `opencv-python`, `rdkit`, `conda`-only packages).

                        ENVIRONMENT CONSTRAINTS:
                        - RAM: 1GB | Execution: 60 seconds.
                        - **Data loading:** Inspect first 5-10 rows (`nrows=10`), then use `usecols` to load only needed columns. Downcast numerics to `float32`. For files >50MB, use `chunksize=10000`.
                        - Prefer CSV over Excel. If Excel is required, limit `nrows=50000`.
                        - Avoid 3-index variables when 2-index suffices (e.g., routing).

                        FILE ACCESS:
                        - Read uploads: `"uploads/filename.csv"`
                        - Save exports: `"exports/filename.csv"` (auto-uploaded to GCS)
                        - Plots are captured automatically; save to exports/ only if user requests a file.

                        FORMATTING:
                        - Use LaTeX notation (e.g., `$x_1 = 5$`, `$\\sum_{{i}} c_i x_i$`) in ALL step descriptions and the final summary whenever presenting mathematical expressions, variable names, or numeric results.

                        DECOMPOSITION PROTOCOL:
                        - **Complex problems** (optimization models, multi-step analysis, data cleaning + modeling): MUST decompose into steps. Step 1 must be "Problem Analysis & Feasibility Check" — paraphrase constraints, do napkin math (demand vs capacity, etc.).
                        - **Trivial problems** (single-formula calculation, one-liner plot, direct lookup): May solve in one step, but do NOT set `is_final_step: true` on first attempt (errors may arise).
                        - A problem is trivial ONLY if it requires no optimization model, no data cleaning, and no multi-part logic.

                        STEP EXECUTION:
                        1. If Step 1: analyze (complex) or code directly (trivial).
                        2. Validate previous step output before proceeding.
                        3. If previous step failed, fix it in the next step (still increment step_id).
                        4. Do not set `is_final_step: true` until code output confirms success.

                        FINAL STEP — SUMMARY:
                        When the problem is solved, create one final step with `"code": ""` and `"is_final_step": true`.
                        - **If the task was a computation/optimization:** The `"description"` must contain ONLY the direct answer to the user's question — specific values, results, and conclusions from the code output. Do NOT describe the process, methodology, or steps taken.
                        - **If the task was a plot/graph:** The `"description"` must simply state: "The requested graph has been plotted and is displayed to the right." Do NOT describe the plot contents.

                        GOAL: Solve this problem: "{user_query}"

                        REFERENCE EXAMPLES:
                        1. {ref1}
                        2. {ref2}

                        CURRENT STATUS:
                        Step history: {json.dumps(step_history)}
                        To-do list: {json.dumps(to_do)}
                        Last code output: {code_output}

                        Respond with a single JSON object:
                        {{
                            "step_id": integer,
                            "description": "string",
                            "code": "python code string",
                            "to_do": ["string", ...],
                            "is_final_step": boolean
                        }}
                        """

                    yield send_sse_event("ping", {"msg": "waiting_for_ai"})

                    accumulated_text = ""
                    try:
                        stream_response = await chat_session.send_message_stream(prompt)
                        async for chunk in stream_response:
                            if chunk.text:
                                accumulated_text += chunk.text
                                yield send_sse_event("token", {"step_number": step_number, "text": chunk.text})
                                await asyncio.sleep(0.01)
                    except Exception as ai_err:
                        logger.error(f"AI Error: {ai_err}")
                        traceback.print_exc()
                        yield send_sse_event("error", {"message": f"AI Error: {str(ai_err)}"})
                        return

                    try:
                        step_data = json_repair.loads(accumulated_text)
                    except Exception as e:
                        logger.error(f"JSON Parse Error: {e}\nPayload: {accumulated_text}")
                        step_data = {"description": "Error parsing AI response", "code": "", "is_final_step": False}

                    if not isinstance(step_data, dict):
                        step_data = {"description": f"Invalid AI Output: {str(step_data)[:100]}", "code": "", "is_final_step": False}

                    to_do = step_data.get("to_do", [])
                    code_to_run = step_data.get("code", "")

                    yield send_sse_event("executing", {"step_number": step_number, "code": code_to_run})
                    yield send_sse_event("ping", {"msg": "executing_code"})

                    execution_result = {"output": "", "error": "", "plots": []}

                    if code_to_run:
                        try:
                            clean_session_id = data.session_id or "fallback_session"

                            resp = await executor_client.post(EXECUTOR_URL, json={
                                "code": code_to_run,
                                "session_id": clean_session_id,
                                "timeout": 120
                            })
                            if resp.status_code == 200:
                                execution_result = resp.json()
                            else:
                                execution_result = {
                                    "output": "",
                                    "error": f"Execution API Error {resp.status_code}: {resp.text[:500]}"
                                }
                        except httpx.TimeoutException:
                            execution_result = {
                                "output": "",
                                "error": "Code execution timed out."
                            }
                        except Exception as exe_err:
                            logger.error(f"Executor Connection Error: {exe_err}")
                            execution_result = {
                                "output": "",
                                "error": f"Execution Connection Failed: {str(exe_err)}"
                            }

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
                    logger.error(f"Critical Loop Error: {loop_error}")
                    traceback.print_exc()
                    yield send_sse_event("error", {"message": f"Internal Server Error: {str(loop_error)}"})
                    return

            yield send_sse_event("done", {"total_steps": len(step_history), "steps": step_history})

        finally:
            await executor_client.aclose()

    return StreamingResponse(
        stream_solution(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "Connection": "keep-alive",
            "X-Accel-Buffering": "no",
        }
    )


@app.post("/api/sessions")
async def get_user_sessions(data: ChatHistoryRequest):
    user_id = data.user_id.strip()
    if not user_id:
        raise HTTPException(status_code=400, detail="User ID is required")
    try:
        sessions = history_manager.fetch_user_sessions(user_id)
        return {"sessions": sessions, "count": len(sessions)}
    except Exception as e:
        logger.error(f"Fetch Sessions Error: {e}")
        raise HTTPException(status_code=500, detail=f"Error fetching sessions: {str(e)}")


@app.post("/api/sessions/create")
async def create_new_session(data: CreateSessionRequest):
    try:
        session_id = history_manager.create_chat_session(data.user_id, data.title)
        return {"success": True, "session_id": session_id}
    except Exception as e:
        logger.error(f"Create Session Error: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@app.post("/api/chathistory")
async def get_chat_messages(data: ChatHistoryRequest):
    user_id = data.user_id.strip()
    session_id = data.session_id
    if not user_id or not session_id:
        raise HTTPException(status_code=400, detail="User ID and Session ID are required")
    try:
        messages = history_manager.fetch_session_messages(user_id, session_id)
        return {"history": messages, "count": len(messages)}
    except Exception as e:
        logger.error(f"Fetch History Error: {e}")
        raise HTTPException(status_code=500, detail=f"Error fetching messages: {str(e)}")


@app.post("/api/chathistory/save")
async def save_chat_message(data: SaveMessageRequest):
    try:
        history_manager.add_message(
            user_id=data.user_id,
            session_id=data.session_id,
            role=data.role,
            content=data.content
        )
        return {"success": True}
    except Exception as e:
        logger.error(f"Save Message Error: {e}")
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
    if data.session_id:
        try:
            async with httpx.AsyncClient() as client:
                await client.delete(f"{EXECUTOR_HOST}/cleanup/{data.session_id}")
            return {"status": "success", "message": "Executor disk space reclaimed."}
        except Exception as e:
            logger.error(f"Silent cleanup failed: {e}")
            return {"status": "error", "message": str(e)}
    return {"status": "noop"}