import os
import json
import requests
from dotenv import load_dotenv
from fastapi import FastAPI, HTTPException 
from fastapi.middleware.cors import CORSMiddleware 
from fastapi.responses import StreamingResponse
from pydantic import BaseModel
import ollama
from pinecone import Pinecone
import google.generativeai as genai

# -- CONFIGURATION --

load_dotenv()
GOOGLE_API_KEY = os.getenv("GOOGLE_API_KEY")
PINECONE_API_KEY = os.getenv("PINECONE_API_KEY")
EXECUTOR_URL = "http://localhost:8000/execute"

if not GOOGLE_API_KEY:
    raise ValueError("No API key found. Check your .env file.")

genai.configure(api_key=GOOGLE_API_KEY)

pc = Pinecone(api_key=PINECONE_API_KEY)
index_name = "math-questions"
index = pc.Index(index_name)

CHAT_MODEL_NAME = "gemini-2.5-flash"
EMBEDDING_MODEL_NAME = "hf.co/CompendiumLabs/bge-base-en-v1.5-gguf"

# --- FastAPI app ---
app = FastAPI() 
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)

# -------------------- Pydantic Models --------------------
class RetrieveRequest(BaseModel):
    query: str

class SolveRequest(BaseModel):
    problem: str = ""
    second_problem: str = ""
    user_query: str

# -------------------- Helper Functions --------------------
def send_sse_event(event_type: str, data: dict) -> str:
    """Format data as Server-Sent Event"""
    return f"event: {event_type}\ndata: {json.dumps(data)}\n\n"

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


@app.post("/api/solve")
async def solve(data: SolveRequest):
    user_query = data.user_query.strip()
    if not user_query:
        raise HTTPException(status_code=400, detail="User query is required")

    problem1 = data.problem
    problem2 = data.second_problem

    async def stream_solution():
        step_history = []
        finished = False
        code_output = "None (Start of problem)"
        max_steps = 10
        current_loop = 0

        model = genai.GenerativeModel(
            model_name=CHAT_MODEL_NAME,
            generation_config={"response_mime_type": "application/json"},
        )
        chat_session = model.start_chat(history=[])

        while not finished and current_loop < max_steps:
            step_number = current_loop + 1
            
            # Notify client that we're starting a new step
            yield send_sse_event("step_start", {
                "step_number": step_number,
                "status": "generating"
            })

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
            
            print(f"--- Gemini Generating Step {step_number} (Streaming) ---")
            
            try:
                # Use streaming for Gemini response
                response = chat_session.send_message(prompt, stream=True)
                accumulated_text = ""
                
                for chunk in response:
                    if chunk.text:
                        accumulated_text += chunk.text
                        # Stream each token/chunk to client
                        yield send_sse_event("token", {
                            "step_number": step_number,
                            "text": chunk.text,
                            "accumulated": accumulated_text
                        })
                
                # Parse the complete JSON response
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

            # Notify client that we're executing code
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

            # Send completed step to client
            yield send_sse_event("step_complete", {
                "step": full_step_record,
                "step_number": step_number
            })

            if step_data.get("is_final_step", False):
                finished = True

            current_loop += 1

        # Signal completion
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
            "X-Accel-Buffering": "no",  # Disable nginx buffering
        }
    )


# -------------------- Run --------------------
# Run with: uvicorn main:app --reload --port 5000