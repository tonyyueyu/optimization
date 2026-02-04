import os
import json
from pinecone import Pinecone, ServerlessSpec
from google import genai
from dotenv import load_dotenv

# Load API Keys from .env
load_dotenv()
GOOGLE_API_KEY = os.getenv("GOOGLE_API_KEY")
PINECONE_API_KEY = os.getenv("PINECONE_API_KEY")

# Configuration (Must match backend)
INDEX_NAME = "math-questions"
DIMENSIONS = 768 # text-embedding-004 uses 768
EMBEDDING_MODEL = "text-embedding-004"

# Initialize Clients
pc = Pinecone(api_key=PINECONE_API_KEY)
genai_client = genai.Client(api_key=GOOGLE_API_KEY)

# 1. Create Index if it doesn't exist
if INDEX_NAME not in [i.name for i in pc.list_indexes()]:
    print(f"Creating index {INDEX_NAME}...")
    pc.create_index(
        name=INDEX_NAME,
        dimension=DIMENSIONS,
        metric="cosine",
        spec=ServerlessSpec(cloud="aws", region="us-east-1")
    )

index = pc.Index(INDEX_NAME)

index.delete(delete_all=True)  # Clear existing data

# 2. Load Dataset
with open('dataset-template.json', 'r') as f:
    data = json.load(f)

print(f"Embedding and Uploading {len(data)} problems...")

for item in data:
    # 3. Generate Embedding using Google (Match the backend!)
    embed_resp = genai_client.models.embed_content(
        model=EMBEDDING_MODEL,
        contents=item["problem"],
        config={'task_type': 'RETRIEVAL_DOCUMENT'}
    )
    embedding = embed_resp.embeddings[0].values

    # 4. Prepare Metadata
    # We pull 'tags' out to the top level so Pinecone can filter on it.
    # We keep the full 'json' string so the backend can easily parse it.
    metadata = {
        "tags": item.get("tags", []), 
        "json": json.dumps(item)
    }

    # 5. Upsert to Pinecone
    index.upsert(vectors=[{
        "id": str(item["id"]), 
        "values": embedding, 
        "metadata": metadata
    }])
    print(f"✅ Uploaded Problem {item['id']}: {item.get('tags', [])}")

print("\nFinished! Your RAG database is now filterable by tags.")