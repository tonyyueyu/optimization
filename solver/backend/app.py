from flask import Flask, request, jsonify
import json
import ollama
from pinecone import Pinecone

PINECONE_API_KEY = "pcsk_bpvp5_KwTepQWna8UPTFAzZCkCTSQqMnLUNwtwCh3nhm1Rx2ogExfb5BpHQLGCVKYf4Bz"

index_name = "math-questions"

pc = Pinecone(api_key=PINECONE_API_KEY)

index = pc.Index(index_name)

EMBEDDING_MODEL = 'hf.co/CompendiumLabs/bge-base-en-v1.5-gguf'

app = Flask(__name__)

@app.route("/api/retrieve", methods=["POST"])
def retrieve():
    data = request.json
    query = data.get("query", "")
    if not query:
        return jsonify({"error": "Query is required"}), 400

    query_embed = ollama.embed(model=EMBEDDING_MODEL, input=query)["embeddings"][0]

    results = index.query(vector=query_embed, top_k=2, include_metadata=True)

    res = []
    for match in results['matches']:
        raw_json = match['metadata']['json']
        obj = json.loads(raw_json)
        res.append({
            "score": match["score"],
            "id": obj["id"],
            "problem": obj["problem"],
            "solution": obj.get("solution"),
            "steps": obj.get("steps")
        })

    return jsonify(res)

@app.route("/api/solve", methods=["POST"])
def solve():
    data = request.json
    problem1 = data.get("problem", "")
    problem2 = data.get("second_problem", "")
    usery_query = data.get("user_query", "")

    if(not usery_query):
        return jsonify({"error": "User query is required"}), 400

    step_history = []
    GEMINI_MODEL = 'gemini-3.0'
    finished = False
    code_output = None

    while not finished:
        prompt = f"""
            Solve the following problem using similar formatting to the two example problems provided. Ensure to write python code 
            for all numerical steps. Output one step at a time in a JSON format with the step number, description, code, and whether 
            or not the step is the final step. I will then return you the output of your code from a Jupyter notebook and in response 
            you will qualitatively validate the code output and the step as a whole and output the next step as another JSON file. Your 
            final answer for the problem should be the output of the last code block. Validate the most recent step, if any, before proceeding to the next step

            User Query (Problem to solve): {usery_query}
            Example Solved Problems:
            1. Problem: {problem1}
            2. Problem: {problem2}

            Previous steps output: {json.dumps(step_history)}

            Previous code output: {code_output}

            Provide the next step in only JSON format like below:
            {{
                "description": "<Describe the step in words>",
                "code": "<Python code to run, empty if not applicable>",
                "is_final_step": "<true/false, is this the last step for this problem>"
            }}
            """
        response = ollama.chat(model=GEMINI_MODEL, messages=[{"role": "user", "content": prompt}])
        content = response.get("content", "")

        try:
            step = json.loads(content)
        except json.JSONDecodeError:
            step = {
                "description": content,
                "code": "",
                "is_final_step": True
            }
        
        code_output = None
        #run the code and save teh output to code_output

        if step.get("is_final_step", False):
            finished = True
        step_history.append(step)
        
        


if __name__ == "__main__":
    app.run(debug=True, port=5000)
