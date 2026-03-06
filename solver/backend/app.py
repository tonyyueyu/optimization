import os
import json
import httpx
import asyncio
import time
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

isCloud = False
if isCloud:
    # EXECUTOR_HOST = "https://executor-service-696616516071.us-west1.run.app"
    #  EXECUTOR_HOST = "https://executor-service-test-696616516071.us-west1.run.app"
    EXECUTOR_HOST = "https://executor-service-dev-s7hxkkor4q-uw.a.run.app"
else:
    EXECUTOR_HOST = "http://executor:8000"
EXECUTOR_URL = f"{EXECUTOR_HOST}/execute"
CHAT_MODEL_NAME = "gemini-3-flash-preview"
EMBEDDING_MODEL_NAME = "models/gemini-embedding-001"
storage_client = None
raw_bucket_name = os.getenv("GCS_BUCKET_NAME")
GCS_BUCKET_NAME = raw_bucket_name.strip('"\n\r ') if raw_bucket_name else None

SOLVER_SYSTEM_PROMPT = """You are a Math Optimization & CAD Code Solver.

ENVIRONMENT — PREINSTALLED LIBRARIES (use these directly, no pip install needed):
- **Data:** polars (preferred), pandas, numpy, pyarrow
- **Optimization:** pyomo + ipopt/highs/glpk, cvxpy, scipy.optimize, scikit-optimize
- **ML/Prediction:** xgboost (preferred), lightgbm, scikit-learn, pytorch, jax
- **CAD/Geometry:** cadquery (preferred for any 3D geometry, parts, assemblies, solid modeling)
- **Math/Symbolic:** sympy, numpy, scipy
- **Viz:** matplotlib, seaborn, plotly

pip install is ONLY for packages NOT in the list above. Never pip install anything already preinstalled.

LIBRARY SELECTION — DECISION TREE (follow strictly):
1. Does the problem involve solid modeling, parts, assemblies, shapes, or manufacturing?
   → **cadquery**. Do not use other libraries for CAD interrogation or generation.
2. Does the problem involve LP, MIP, MILP, MINLP, or structured mathematical optimization?
   → **Pyomo** with the strongest available solver: HiGHS > IPOPT > GLPK.
   → Use cvxpy as an alternative for convex problems.
   → NEVER default to scipy.optimize for problems that have a clear constraint/objective structure.
3. Does the problem involve nonlinear optimization or NLP?
   → **Pyomo + IPOPT**.
4. Does the problem involve tabular ML / prediction / regression / classification?
   → **XGBoost** or **LightGBM** (not scikit-learn, unless ensemble methods are insufficient).
5. Does the problem involve large numerical arrays, autodiff, or JIT performance?
   → **JAX** (preferred over numpy for performance-critical math).
6. Is the problem a simple root-find, curve-fit, or 1D integral with no structure?
   → scipy.optimize is acceptable here only.
7. Does the problem involve tabular data loading/wrangling?
   → **Polars** (preferred over pandas for performance).

SOLVER CONFIGURATION (MANDATORY for all optimization):
- Always set a time limit: e.g. `solver.options['TimeLimit'] = 30` (HiGHS/Gurobi), `solver.options['max_cpu_time'] = 30` (IPOPT).
- Always check termination condition and print solver status before reporting results.
- For HiGHS via Pyomo: `SolverFactory('appsi_highs')` or `SolverFactory('highs')`.
- For IPOPT via Pyomo: `SolverFactory('ipopt')`.

CADQUERY USAGE:
- Use CadQuery for ANY problem involving: 3D shapes, cross-sections, volumes, surface areas, mechanical parts, assemblies, extrusions, sweeps, fillets, holes, or manufacturing geometry.
- Export results: `shape.val().exportStl("exports/output.stl")` or `.exportStep("exports/output.step")`.
- Compute geometric properties using CadQuery's built-in `.val().Volume()`, `.val().Area()`, bounding box, etc.

IMPORTANT PLOTTING RULES:
1. Standard Plots: Use matplotlib or seaborn for logic that needs to show up immediately in the "Plots" area, do not save the pngs unless they are explicitly requested by the user.
2. Plotly: If you use Plotly, you MUST save the figure as a static image for it to be captured, OR save it as an HTML file in exports/.

ROLE:
- **SYNTAX:** Mirror the REFERENCE EXAMPLES for variable definitions and code structure.
- **LOGIC:** Derive objectives, constraints, and data STRICTLY from the USER QUERY. Do NOT copy constraints from references.
- **Unit Check:** Scale inputs if units differ between query and references.
- **One Step at a Time:** Only output one step at a time NOT THE FULL JSON.

ENVIRONMENT CONSTRAINTS:
- RAM: 1GB | Execution: 60 seconds.
- **Data loading:** Inspect first 5-10 rows, use `usecols` to load only needed columns. Prefer Polars; downcast to float32 if using pandas. For files >50MB, use chunked reads.
- Prefer CSV over Excel. If Excel is required, limit `nrows=50000`.
- Avoid 3-index variables when 2-index suffices.

FILE ACCESS:
- **Read uploads:** Uploaded files are NOT available on the local filesystem. Instead, they are provided in the prompt as GCS Signed URLs. You MUST read them directly from these URLs using appropriate libraries (e.g., `pd.read_csv("URL")`, `requests.get("URL")`, etc.).
- **Save exports:** Continue to save files to the `"exports/"` directory (e.g., `"exports/output.csv"`). These will be automatically captured and uploaded.
- Plots captured automatically; save to exports/ only if user requests a file.

FORMATTING:
- Use LaTeX notation (e.g., `$x_1 = 5$`, `$\\sum_{{i}} c_i x_i$`) in ALL step descriptions and the final summary whenever presenting mathematical expressions, variable names, or numeric results.

DECOMPOSITION PROTOCOL:
- **Complex problems** (optimization models, multi-step analysis, CAD geometry + calculation, data cleaning + modeling): MUST decompose into steps. Step 1 must be "Problem Analysis & Feasibility Check" — paraphrase constraints, identify which library applies per the decision tree above, do napkin math.
- **Trivial problems** (single-formula calculation, simple plots, direct lookup): May solve in one step, but do NOT set `is_final_step: true` on first attempt.
- A problem is trivial ONLY if it requires no complex optimization model, no CAD geometry, and no multi-part logic.

STEP EXECUTION:
1. If Step 1: analyze (complex) or code directly (trivial).
2. Validate previous step output before proceeding.
3. If previous step failed, fix it in the next step (still increment step_id).
4. Do not set `is_final_step: true` until the PREVIOUS step's code output confirms completion.

MANDATORY FIRST STEP:
Your FIRST step (step_id: 1) MUST be "Problem Analysis & Feasibility Check":
- Paraphrase the problem constraints in your own words
- Identify which library/solver applies using the Decision Tree below
- Perform napkin math to sanity-check feasibility (bounds, variable counts, expected magnitude of objective)
- Do NOT write solution code in this step — analysis only
- Set code to "" or a simple data-inspection snippet at most
A problem is trivial ONLY if it requires a single formula, a simple plot, or a direct lookup with no optimization model, no CAD geometry, and no multi-part logic.

FINAL STEP — SUMMARY:
When the problem is solved, create one final step with `"code": ""` and `"is_final_step": true`.
- **Computation/optimization:** `"description"` must contain ONLY the direct answer — specific values, results, conclusions from code output. Do NOT describe process or methodology.
- **Plot/graph:** `"description"` must simply state: "The requested graph has been plotted and is displayed to the right."
- **CAD output:** `"description"` must state the exported file name and key geometric properties (volume, area, dimensions) extracted from CadQuery.

OUTPUT FORMAT:
You must ALWAYS respond with a single JSON object with exactly these fields:
- step_id (integer): the current step number
- description (string): what this step does or the final answer
- code (string): Python code to execute, or empty string for final summary
- to_do (array of strings): remaining tasks after this step
- is_final_step (boolean): true only when the problem is fully solved"""

SOLVER_RESPONSE_SCHEMA = types.Schema(
    type=types.Type.OBJECT,
    required=["step_id", "description", "code", "to_do", "is_final_step"],
    properties={
        "step_id": types.Schema(type=types.Type.INTEGER),
        "description": types.Schema(type=types.Type.STRING),
        "code": types.Schema(type=types.Type.STRING),
        "to_do": types.Schema(
            type=types.Type.ARRAY,
            items=types.Schema(type=types.Type.STRING),
        ),
        "is_final_step": types.Schema(type=types.Type.BOOLEAN),
    },
)

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


class UserConnectionManager:
    def __init__(self):
        self.connections: Dict[str, Any] = {}
        self.timeout_seconds = 30 * 60  # 30 minutes

    async def get_client(self, connection_id: str) -> httpx.AsyncClient:
        now = time.time()
        if connection_id not in self.connections:
            client = httpx.AsyncClient(timeout=httpx.Timeout(600.0, connect=60.0, read=600.0, write=60.0, pool=60.0))
            task = asyncio.create_task(self._keep_alive_loop(connection_id, client))
            self.connections[connection_id] = {
                "client": client,
                "last_active": now,
                "keep_alive_task": task
            }
            logger.info(f"🆕 Created new executor connection for: {connection_id}")
        else:
            self.connections[connection_id]["last_active"] = now
            logger.info(f"♻️ Reusing executor connection for: {connection_id}")
            
        return self.connections[connection_id]["client"]

    async def _keep_alive_loop(self, connection_id: str, client: httpx.AsyncClient):
        try:
            while True:
                await asyncio.sleep(60)
                now = time.time()
                conn_info = self.connections.get(connection_id)
                if not conn_info:
                    break
                
                if now - conn_info["last_active"] > self.timeout_seconds:
                    logger.info(f"⏳ Connection {connection_id} inactive for 30 mins. Closing.")
                    await self.close_connection(connection_id)
                    break
                
                try:
                    await client.get(f"{EXECUTOR_HOST}/ping", timeout=10.0)
                    logger.debug(f"💓 Keep-alive sent to {connection_id}")
                except Exception as e:
                    logger.warning(f"⚠️ Keep-alive ping failed for {connection_id}: {e}")
        except asyncio.CancelledError:
            pass
        except Exception as e:
            logger.error(f"Keep-alive loop error for {connection_id}: {e}")

    async def close_connection(self, connection_id: str):
        if connection_id in self.connections:
            conn = self.connections.pop(connection_id)
            if not conn["keep_alive_task"].done():
                conn["keep_alive_task"].cancel()
            
            try:
                await conn["client"].aclose()
            except:
                pass
            logger.info(f"🔌 Closed connection map for: {connection_id}")

connection_manager = UserConnectionManager()


class RetrieveRequest(BaseModel):
    query: str

class SolveRequest(BaseModel):
    problem: str = ""
    second_problem: str = ""
    user_query: str
    user_id: Optional[str] = None
    session_id: Optional[str] = None
    chat_history: Optional[List[Dict[str, Any]]] = None
    selected_files: Optional[List[str]] = None

class ChatHistoryRequest(BaseModel):
    user_id: str
    session_id: Optional[str] = None

class BootRequest(BaseModel):
    user_id: str

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
            # Explicitly load the JSON key since we are baking it into the container
            if os.path.exists("gcs-key.json"):
                storage_client = storage.Client.from_service_account_json("gcs-key.json")
            elif os.path.exists("/app/gcs-key.json"): 
                storage_client = storage.Client.from_service_account_json("/app/gcs-key.json")
            else:
                storage_client = storage.Client(project="hippomath") 
        except Exception as e:
            raise RuntimeError(f"GCS Initialization Failed: {str(e)}")
            
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
            method="GET",
            service_account_email="696616516071-compute@developer.gserviceaccount.com"
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
    logger.info(f"📁 [/api/upload] Received file upload req: file={file.filename}, user_id={user_id}, session_id={session_id}")
    try:
        client = get_storage_client()
        if not client:
            raise HTTPException(status_code=503, detail="GCS not available")

        file_content = await file.read()

        bucket = client.bucket(GCS_BUCKET_NAME)
        effective_user_id = user_id or 'anonymous'
        
        prefix = f"{effective_user_id}/{session_id}/"
        blob_path = f"{effective_user_id}/{session_id}/{file.filename}"

        current_usage = sum(
            b.size for b in bucket.list_blobs(prefix=prefix) if b.size
        )
        if current_usage + len(file_content) > STORAGE_LIMIT_BYTES:
            raise HTTPException(status_code=413, detail="1.5GB storage limit exceeded")

        blob = bucket.blob(blob_path)
        blob.upload_from_string(file_content, content_type=file.content_type)

        url = generate_signed_download_url(blob.name)
        if not url:
            url = blob.public_url

        return {
            "status": "success",
            "filename": file.filename,
            "url": url,
            "path": url,
            "id": blob_path
        }
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Upload error: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@app.post("/api/links/save")
async def save_session_link(
    user_id: str = Form(...),
    session_id: str = Form(...),
    name: str = Form(...),
    url: str = Form(...)
):
    """Saves a link as a metadata file in GCS."""
    logger.info(f"🔗 [/api/links/save] Saving link: name={name}, url={url[:50]}..., user_id={user_id}, session_id={session_id}")
    try:
        link_data = {"name": name, "url": url, "type": "link"}
        client = get_storage_client()
        if not client or not GCS_BUCKET_NAME:
            raise HTTPException(status_code=503, detail="GCS not available")

        bucket = client.bucket(GCS_BUCKET_NAME)
        effective_user_id = user_id or 'anonymous'
     
        blob_name = f"{effective_user_id}/{session_id}/{name}.link"
            
        blob = bucket.blob(blob_name)
        blob.upload_from_string(json.dumps(link_data), content_type="application/json")

        return {"status": "success", "filename": name, "storage": "gcs", "id": blob_name}
    except Exception as e:
        logger.error(f"Link save error: {e}")
        raise HTTPException(status_code=500, detail=str(e))

@app.get("/api/files/{session_id}")
async def list_session_files(session_id: str, user_id: str = "anonymous"):
    """Lists files and links uploaded for the given session."""
    logger.info(f"📋 [/api/files] Listing session files: user={user_id}, session={session_id}")
    files = []
    try:
        client = get_storage_client()
        if not client or not GCS_BUCKET_NAME:
             return {"files": [], "status": "error", "message": "GCS not available"}

        bucket = client.bucket(GCS_BUCKET_NAME)
        effective_user_id = user_id or 'anonymous'
        
        logger.info(f"📁 Listing files for user: {effective_user_id} (session: {session_id})")

        prefix = f"{effective_user_id}/{session_id}/"
            
        logger.info(f"🔍 GCS Prefix: {prefix}")
        blobs = bucket.list_blobs(prefix=prefix)
        
        for blob in blobs:
            rel_name = blob.name.replace(f"{effective_user_id}/", "", 1)
            if not rel_name: continue
            
            if "/" in rel_name:
                parts = rel_name.split("/")
                sid = parts[0]
                filename = "/".join(parts[1:])
            else:
                sid = "global"
                filename = rel_name
            
            if filename.endswith(".link"):
                try:
                    content = blob.download_as_string()
                    link_info = json.loads(content)
                    files.append({
                        "name": link_info.get("name", filename.replace(".link", "")),
                        "url": link_info.get("url", "#"),
                        "type": "link",
                        "size": "Link",
                        "id": blob.name,
                        "session_id": sid,
                        "gcs_path": blob.name,
                        "updated": blob.updated.isoformat() if blob.updated else None,
                    })
                except: continue
            else:
                files.append({
                    "name": filename,
                    "size": f"{blob.size / 1024:.1f} KB" if blob.size < 1024 * 1024 else f"{blob.size / (1024 * 1024):.1f} MB",
                    "id": blob.name,
                    "updated": blob.updated.isoformat() if blob.updated else None,
                    "type": "file",
                    "session_id": sid,
                    "gcs_path": blob.name,
                    "url": generate_signed_download_url(blob.name) or blob.public_url
                })
        
        files.sort(key=lambda x: x.get('updated', ''), reverse=True)
        return {"files": files, "status": "success", "storage": "gcs"}
    except Exception as e:
        logger.error(f"Error listing files: {e}")
        return {"files": [], "error": str(e)}

@app.post("/api/files/delete")
async def delete_file(
    user_id: str = Form(...),
    session_id: str = Form(...),
    id: str = Form(...) # Use GCS path as ID
):
    """Manually delete a file or link from GCS."""
    logger.info(f"🗑️ [/api/files/delete] Delete file requested: id={id}, session={session_id}, user={user_id}")
    try:
        client = get_storage_client()
        if not client or not GCS_BUCKET_NAME:
            raise HTTPException(status_code=503, detail="GCS not available")
        
        bucket = client.bucket(GCS_BUCKET_NAME)
        blob = bucket.blob(id)
        if blob.exists():
            blob.delete()
            return {"status": "success", "message": f"Deleted GCS blob {id}"}
        
        return {"status": "error", "message": f"File {id} not found in GCS"}
    except Exception as e:
        logger.error(f"Delete file Error: {e}")
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
                config=types.GenerateContentConfig(response_mime_type="application/json", temperature=1.0)
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
        c_id = data.user_id if data.user_id and data.user_id != 'anonymous' else data.session_id
        client = await connection_manager.get_client(c_id)
        try:
            await client.delete(f"{EXECUTOR_HOST}/cleanup/{data.session_id}")
        except Exception as e:
            logger.warning(f"Executor cleanup failed: {e}")
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
    logger.info(f"🧠 [/api/solve] AI Solve Request started: session_id={data.session_id}, user_id={data.user_id}, query='{user_query}'")
    if not user_query:
        raise HTTPException(status_code=400, detail="User query is required")

    async def stream_solution():

        ref1, ref2 = await get_references(user_query, data.chat_history or [])

        step_history = []

        # Cloud Run session affinity kept alive via UserConnectionManager
        c_id = data.user_id if data.user_id and data.user_id != 'anonymous' else data.session_id
        executor_client = await connection_manager.get_client(c_id)

        try:
            config = types.GenerateContentConfig(
                system_instruction=SOLVER_SYSTEM_PROMPT,
                temperature=0.1,
                response_mime_type="application/json",
                response_schema=SOLVER_RESPONSE_SCHEMA,
                thinking_config=types.ThinkingConfig(include_thoughts=False),
            )

            try:
                http_opts = types.HttpOptions(timeout=600000)
                local_client = genai.Client(
                    api_key=GOOGLE_API_KEY,
                    http_options=http_opts
                )

                chat_session = local_client.aio.chats.create(
                    model=CHAT_MODEL_NAME,
                    history=[],
                    config=config,
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
                    yield send_sse_event("step_start", {"step_number": step_number, "status": "generating", "to_do": to_do})

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

                    # List selected or session files from GCS to provide to AI
                    session_files_context = ""
                    try:
                        sc = get_storage_client()
                        if sc and GCS_BUCKET_NAME:
                            bucket = sc.bucket(GCS_BUCKET_NAME)
                            file_items = []

                            if data.selected_files:
                                for blob_name in data.selected_files:
                                    blob = bucket.blob(blob_name)
                                    if blob.exists():
                                        name = os.path.basename(blob.name)
                                        if name.endswith(".link"):
                                            try:
                                                link_info = json.loads(blob.download_as_string())
                                                file_items.append(f"- [LINK] {link_info.get('name')}: {link_info.get('url')}")
                                            except: pass
                                        else:
                                            url = generate_signed_download_url(blob.name) or blob.public_url
                                            file_items.append(f"- [FILE] {name}: {url}")
                            elif data.session_id:
                                prefix = f"{data.user_id or 'anonymous'}/{data.session_id}/"
                                blobs = bucket.list_blobs(prefix=prefix)
                                for b in blobs:
                                    name = os.path.basename(b.name)
                                    if name.endswith(".link"):
                                        try:
                                            link_info = json.loads(b.download_as_string())
                                            file_items.append(f"- [LINK] {link_info.get('name')}: {link_info.get('url')}")
                                        except: pass
                                    else:
                                        url = generate_signed_download_url(b.name) or b.public_url
                                        file_items.append(f"- [FILE] {name}: {url}")

                            if file_items:
                                session_files_context = "AVAILABLE CONTEXT (Files & Links):\n" + "\n".join(file_items) + "\n\n"
                    except Exception as e:
                        logger.error(f"Failed to list session files for prompt: {e}")

                    prompt = f"""{chat_context}{session_files_context}GOAL: Solve this problem: "{user_query}"

                            REFERENCE EXAMPLES:
                            1. {ref1}
                            2. {ref2}

                            CURRENT STATUS:
                            Step history: {json.dumps(step_history)}
                            To-do list: {json.dumps(to_do)}
                            Last code output: {code_output}"""
                    logger.info(f"📝 [Step {step_number}] Prompt to Gemini:\n{prompt}")
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

                    logger.info(f"🤖 [Step {step_number}] Gemini Response:\n{accumulated_text}")
                    try:
                        step_data = json_repair.loads(accumulated_text)
                    except Exception as e:
                        logger.error(f"JSON Parse Error: {e}\nPayload: {accumulated_text}")
                        step_data = {"description": "Error parsing AI response", "code": "", "is_final_step": False}

                    if not isinstance(step_data, dict):
                        step_data = {"description": f"Invalid AI Output: {str(step_data)[:100]}", "code": "", "is_final_step": False}

                    to_do = step_data.get("to_do", [])
                    code_to_run = step_data.get("code", "")

                    yield send_sse_event("executing", {"step_number": step_number, "code": code_to_run, "to_do": to_do})
                    yield send_sse_event("ping", {"msg": "executing_code"})

                    execution_result = {"output": "", "error": "", "plots": []}

                    if code_to_run:
                        try:
                            clean_session_id = data.session_id or "fallback_session"

                            resp = await executor_client.post(EXECUTOR_URL, json={
                                "code": code_to_run,
                                "session_id": clean_session_id,
                                "timeout": 240
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
                        
                        logger.info(f"⚙️ [Step {step_number}] Execution Response:\n{json.dumps(execution_result, indent=2)}")

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
            
            user_id = data.user_id or 'anonymous'
            if user_id == 'anonymous' or user_id.startswith('anon_'):
                logger.info(f"🧹 Auto-cleaning anonymous session: {data.session_id}")
                try:
                    if data.session_id:
                        sc = get_storage_client()
                        if sc and GCS_BUCKET_NAME:
                            bucket = sc.bucket(GCS_BUCKET_NAME)
                            prefix = f"{user_id}/"
                            blobs = bucket.list_blobs(prefix=prefix)
                            for b in blobs:
                                b.delete()
                        
                        history_manager.delete_session('anonymous', data.session_id)
                        try:
                            await executor_client.delete(f"{EXECUTOR_HOST}/cleanup/{data.session_id}")
                        except Exception as e:
                            logger.warning(f"Executor cleanup failed: {e}")
                except Exception as cleanup_err:
                    logger.error(f"Failed to auto-clean anonymous session: {cleanup_err}")

        finally:
            pass # Client is managed by UserConnectionManager

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
    logger.info(f"📅 [/api/sessions] Fetching sessions for user: {user_id}")
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
            c_id = user_id if user_id and user_id != 'anonymous' else data.session_id
            client = await connection_manager.get_client(c_id)
            try:
                await client.delete(f"{EXECUTOR_HOST}/cleanup/{data.session_id}")
            except Exception as e:
                logger.warning(f"Executor cleanup failed: {e}")
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
            c_id = data.user_id if data.user_id and data.user_id != 'anonymous' else data.session_id
            client = await connection_manager.get_client(c_id)
            await client.delete(f"{EXECUTOR_HOST}/cleanup/{data.session_id}")
            return {"status": "success", "message": "Executor disk space reclaimed."}
        except Exception as e:
            logger.error(f"Silent cleanup failed: {e}")
            return {"status": "error", "message": str(e)}
    return {"status": "noop"}

@app.post("/api/boot")
async def boot_executor(data: BootRequest):
    user_id = data.user_id.strip()
    c_id = user_id if user_id and user_id != 'anonymous' else "anonymous"
    logger.info(f"🚀 [/api/boot] Booting executor container for user: {c_id}")
    try:
        client = await connection_manager.get_client(c_id)
        # Actively ping it right now so Cloud Run container wakes up
        await client.get(f"{EXECUTOR_HOST}/ping", timeout=10.0)
        return {"status": "success", "message": "Executor booted and warmed up."}
    except Exception as e:
        logger.error(f"Boot Error: {e}")
        return {"status": "error", "message": str(e)}