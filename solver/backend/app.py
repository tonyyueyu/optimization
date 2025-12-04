import os
import json
import requests
from dotenv import load_dotenv
from fastapi import FastAPI, HTTPException 
from fastapi.middleware.cors import CORSMiddleware 
from pydantic import BaseModel
import ollama
from pinecone import Pinecone
import google.generativeai as genai
from history_manager import HistoryManager
from fastapi.responses import StreamingResponse
import asyncio

# -- CONFIGURATION --

load_dotenv()
GOOGLE_API_KEY = os.getenv("GOOGLE_API_KEY")
PINECONE_API_KEY = os.getenv("PINECONE_API_KEY")
EXECUTOR_URL = "http://localhost:8000/execute"

if not GOOGLE_API_KEY:
    raise ValueError("No API key found. Check your .env file.")

genai.configure(api_key=GOOGLE_API_KEY)
print("Available Gemini Models:")
print(genai.list_models())

pc = Pinecone(api_key=PINECONE_API_KEY)
index_name = "math-questions"
index = pc.Index(index_name)

CHAT_MODEL_NAME = "gemini-2.5-flash"
EMBEDDING_MODEL_NAME = "hf.co/CompendiumLabs/bge-base-en-v1.5-gguf"
history_manager = HistoryManager()

# --- FastAPI app ---
app = FastAPI() 
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)

# -------------------- Pydantic Models --------------------
class RetrieveRequest(BaseModel):  # Added to replace Flask request.json
    query: str

class SolveRequest(BaseModel):  # Added to replace Flask request.json
    problem: str = ""
    second_problem: str = ""
    user_query: str
    session_id: str = "default_session"

# -------------------- API Endpoints --------------------
@app.post("/api/retrieve")
async def retrieve(data: RetrieveRequest):
    query = data.query.strip()
    if not query:
        raise HTTPException(status_code=400, detail="Query is required")
    
    try:
        print(f"Embedding query with: {EMBEDDING_MODEL_NAME}")
        embed_resp = ollama.embed(model=EMBEDDING_MODEL_NAME, input=query)
        query_embed = embed_resp["embeddings"][0]

        results = index.query(vector=query_embed, top_k=2, include_metadata=True)

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
        print(f"Retrieval Error: {e}")
        raise HTTPException(status_code=500, detail=str(e))

from fastapi.responses import StreamingResponse  # Added for streaming
import asyncio  # Added for async generator

@app.post("/api/solve")
async def solve(data: SolveRequest):
    user_query = data.user_query.strip()
    session_id = data.session_id

    if not user_query:
        raise HTTPException(status_code=400, detail="User query is required")

    problem1 = data.problem
    problem2 = data.second_problem

    step_history = []
    finished = False
    code_output = "None (Start of problem)"
    max_steps = 10
    current_loop = 0

    model = genai.GenerativeModel(
        model_name=CHAT_MODEL_NAME,
        generation_config={"response_mime_type": "application/json", "stream": True},  # Changed: enable streaming
    )
    
    past_history = history_manager.get_history(session_id)
    print(f"Loaded {len(past_history)} past messages for session: {session_id}")

    chat_session = model.start_chat(history=past_history)

    async def event_generator():  # Added: async generator for streaming
        nonlocal finished, current_loop, code_output  # Added: allow modifying outer vars

        while not finished and current_loop < max_steps:
            prompt = f"""
            You are a Math Optimization Code Solver. Follow the reference examples to solve the user's problem step-by-step by generating Python code snippets.
            
            GOAL: Solve this problem: "{user_query}"
            
            REFERENCE EXAMPLES:
            1. {problem1}
            2. {problem2}

            CURRENT STATUS:
            History of steps taken: {json.dumps(step_history)}
            Output of the LAST executed code block: {code_output}

            INSTRUCTION:
            1. Validate the last step based on the code output.
            2. Generate the NEXT step. Use the description section as your scratchpad. Write out your reasoning verbosely before writing your code.
            3. Output strict JSON.

            JSON SCHEMA:
            {{
                "step_id": integer,
                "description": "string",
                "code": "python code string",
                "is_final_step": boolean
            }}
            """
            print(f"--- Gemini Generating Step {current_loop + 1} ---")
            try:
                async for chunk in chat_session.stream_message(prompt):  # Changed: stream token chunks
                    yield f"data: {chunk}\n\n"  # Changed: stream chunk to client immediately
            except Exception as e:
                yield f"data: ERROR: {str(e)}\n\n"  # Changed: send errors as stream
                break

            try:
                step_data = json.loads(chat_session.last_response_text)
            except Exception as e:
                yield f"data: ERROR parsing final JSON: {str(e)}\n\n"
                break

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

            yield f"data: {json.dumps(full_step_record)}\n\n"

            if step_data.get("is_final_step", False):
                finished = True

            current_loop += 1

        history_manager.save_history(session_id, chat_session)
        print(f"Saved updated history for session: {session_id}")

    return StreamingResponse(event_generator(), media_type="text/event-stream") 
# -------------------- Run --------------------
# Run with: uvicorn main:app --reload --port 5000
