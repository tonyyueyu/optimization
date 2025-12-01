import os
import json
from flask import Flask, request, jsonify
from flask_cors import CORS
import ollama
import json
from pinecone import Pinecone
import google.generativeai as genai
import requests
from dotenv import load_dotenv

# -- CONFIGURATION --

load_dotenv()
GOOGLE_API_KEY = os.getenv("GOOGLE_API_KEY")
PINECONE_API_KEY = (
    "pcsk_bpvp5_KwTepQWna8UPTFAzZCkCTSQqMnLUNwtwCh3nhm1Rx2ogExfb5BpHQLGCVKYf4Bz"
)
EXECUTOR_URL = "http://localhost:8000/execute"

if not GOOGLE_API_KEY:
    raise ValueError("No API key found. Check your .env file.")
genai.configure(api_key=GOOGLE_API_KEY)
print("Available Gemini Models:")
print(genai.list_models())
pc = Pinecone(api_key=PINECONE_API_KEY)


index_name = "math-questions"

index = pc.Index(index_name)

# Model Settings
# Use 'gemini-2.5-pro'
# These models support Native JSON mode.
CHAT_MODEL_NAME = "gemini-2.5-flash"
EMBEDDING_MODEL_NAME = "hf.co/CompendiumLabs/bge-base-en-v1.5-gguf"


app = Flask(__name__)
CORS(app)


@app.route("/api/retrieve", methods=["POST"])
def retrieve():
    data = request.json
    query = data.get("query", "")
    if not query:
        return jsonify({"error": "Query is required"}), 400
    try:
        print(f"Embedding query with: {EMBEDDING_MODEL_NAME}")
        embed_resp = ollama.embed(model=EMBEDDING_MODEL_NAME, input=query)
        query_embed = embed_resp["embeddings"][0]

        results = index.query(vector=query_embed, top_k=2, include_metadata=True)

        res = []
        for match in results["matches"]:
            if "metadata" in match and "json" in match["metadata"]:
                try:
                    obj = json.loads(match["metadata"]["json"])
                    res.append(
                        {
                            "score": match["score"],
                            "id": obj.get("id"),
                            "problem": obj.get("problem"),
                            "solution": obj.get("solution"),
                            "steps": obj.get("steps"),
                        }
                    )
                except:
                    continue
        return jsonify(res)
    except Exception as e:
        print(f"Retrieval Error: {e}")
        return jsonify({"error": str(e)}), 500


@app.route("/api/solve", methods=["POST"])
def solve():
    data = request.json
    problem1 = data.get("problem", "")
    problem2 = data.get("second_problem", "")
    user_query = data.get("user_query", "")

    if not user_query:
        return jsonify({"error": "User query is required"}), 400

    step_history = []
    finished = False
    code_output = "None (Start of problem)"
    max_steps = 10
    current_loop = 0

    # Configure the Chat Model
    model = genai.GenerativeModel(
        model_name=CHAT_MODEL_NAME,
        generation_config={"response_mime_type": "application/json"},
    )

    # Initialize Chat Session (keeps internal context easier)
    chat_session = model.start_chat(history=[])

    # Prompting Loop
    while not finished and current_loop < max_steps:
        # Construct the prompt
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

        # Call LLM to get next step
        try:
            response = chat_session.send_message(prompt)
            step_data = json.loads(response.text)
        except Exception as e:
            print(f"Gemini Error: {e}")
            return jsonify({"error": f"Failed to generate step from AI: {e}"}), 500

        # Execute code from step
        print(f"Sending code to Docker: {step_data.get('code')}")
        try:
            # Send code to the Docker container via HTTP
            docker_response = requests.post(
                EXECUTOR_URL,
                json={"code": step_data.get("code", "")},
                timeout=30,  # Wait up to 30s for math to finish
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

        # Record Step
        full_step_record = {
            "step_id": step_data.get("step_id"),
            "description": step_data.get("description"),
            "code": step_data.get("code"),
            "output": execution_result["output"],
            "error": execution_result["error"],
        }
        step_history.append(full_step_record)

        # Check for completion
        if step_data.get("is_final_step", False):
            finished = True

        current_loop += 1

    return jsonify({"steps": step_history})


if __name__ == "__main__":
    app.run(debug=True, port=5000)
