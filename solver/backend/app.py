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

if __name__ == "__main__":
    app.run(debug=True, port=5000)
