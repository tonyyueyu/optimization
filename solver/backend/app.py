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
from typing import Union, Dict, Any
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
origins = [
    "http://localhost:5173",  # Vite default
    "http://127.0.0.1:5173",  # IP default
    "http://localhost:3000",  # React Create App default
]

app.add_middleware(
    CORSMiddleware,
    allow_origins=origins, 
    allow_credentials=True,
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
        generation_config={"response_mime_type": "application/json", "stream": True},  # streaming enabled
    )
    
    past_history = history_manager.get_history(session_id)
    print(f"Loaded {len(past_history)} past messages for session: {session_id}")

    chat_session = model.start_chat(history=past_history)

    async def event_generator():
        nonlocal finished, current_loop, code_output

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
                async for token in chat_session.stream_message(prompt):
                    yield f"data: {json.dumps({'type': 'token', 'content': token})}\n\n"
            except Exception as e:
                yield f"data: {json.dumps({'type': 'error', 'content': str(e)})}\n\n"
                break

            try:
                step_data = json.loads(chat_session.last_response_text)
            except Exception as e:
                yield f"data: {json.dumps({'type': 'error', 'content': f'Error parsing JSON: {str(e)}'})}\n\n"
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

            yield f"data: {json.dumps({'type': 'step', 'content': full_step_record})}\n\n"

            if step_data.get("is_final_step", False):
                finished = True

            current_loop += 1

        history_manager.save_history(session_id, chat_session)
        print(f"Saved updated history for session: {session_id}")
        return StreamingResponse(event_generator(), media_type="text/event-stream")

@app.get("/api/history/{session_id}")
async def get_chat_history(session_id: str):
    try:
        history = history_manager.get_history(session_id)
        
        formatted_history = []
        for msg in history:
            content_text = msg.get("parts", [""])[0]
            role = "assistant" if msg["role"] == "model" else "user"
            
           
            if role == "assistant":
                try:
                    # Clean up markdown code fences if Gemini added them (e.g. ```json ... ```)
                    clean_text = content_text.replace("```json", "").replace("```", "").strip()
                    json_data = json.loads(clean_text)
                    
                    
                    if "step_id" in json_data or "steps" in json_data:
                         
                         steps_list = json_data.get("steps", [json_data]) 
                         
                         formatted_history.append({
                            "role": role,
                            "type": "steps", # Tell frontend to use the Step Renderer
                            "steps": steps_list,
                            "content": "Restored solution steps" 
                         })
                         continue # Skip the default append
                except json.JSONDecodeError:
                    pass

            formatted_history.append({
                "role": role,
                "type": "text",
                "content": content_text,
            })
            
        return formatted_history
    except Exception as e:
        print(f"History Error: {e}")
        raise HTTPException(status_code=500, detail=str(e))
    
@app.get("/api/chat_map/")
async def get_chat_history(session_id: str):
    try:
        history = history_manager.get_history(session_id)
        
        formatted_history = []
        for msg in history:
            content_text = msg.get("parts", [""])[0]
            role = "assistant" if msg["role"] == "model" else "user"
            
           
            if role == "assistant":
                try:
                    # Clean up markdown code fences if Gemini added them (e.g. ```json ... ```)
                    clean_text = content_text.replace("```json", "").replace("```", "").strip()
                    json_data = json.loads(clean_text)
                    
                    
                    if "step_id" in json_data or "steps" in json_data:
                         
                         steps_list = json_data.get("steps", [json_data]) 
                         
                         formatted_history.append({
                            "role": role,
                            "type": "steps", # Tell frontend to use the Step Renderer
                            "steps": steps_list,
                            "content": "Restored solution steps" 
                         })
                         continue # Skip the default append
                except json.JSONDecodeError:
                    pass

            formatted_history.append({
                "role": role,
                "type": "text",
                "content": content_text,
            })
            
        return formatted_history
    except Exception as e:
        print(f"History Error: {e}")
        raise HTTPException(status_code=500, detail=str(e))

# -------------------- Run --------------------
# Run with: uvicorn main:app --reload --port 5000
