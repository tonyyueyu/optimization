import os
import json
import time
from pinecone import Pinecone, ServerlessSpec
from google import genai
from google.genai import types 
from dotenv import load_dotenv

# Load API Keys
load_dotenv()
GOOGLE_API_KEY = os.getenv("GOOGLE_API_KEY")
PINECONE_API_KEY = os.getenv("PINECONE_API_KEY")

# --- CONFIGURATION ---
INDEX_NAME = "math-questions"
DIMENSIONS = 3072  # Native size for gemini-embedding-001
EMBEDDING_MODEL = "models/gemini-embedding-001"

# Initialize Clients
pc = Pinecone(api_key=PINECONE_API_KEY)
genai_client = genai.Client(api_key=GOOGLE_API_KEY)

# 1. Index Management (CRITICAL: Delete old index if dimensions don't match)
existing_indexes = [i.name for i in pc.list_indexes()]

if INDEX_NAME in existing_indexes:
    idx_info = pc.describe_index(INDEX_NAME)
    if idx_info.dimension != DIMENSIONS:
        print(f"⚠️ Index exists but has wrong dimensions ({idx_info.dimension}). Deleting and recreating...")
        pc.delete_index(INDEX_NAME)
        time.sleep(5) # Wait for deletion to propagate
        create_new = True
    else:
        print(f"Index {INDEX_NAME} exists with correct dimensions. Clearing data...")
        index = pc.Index(INDEX_NAME)
        index.delete(delete_all=True)
        create_new = False
else:
    create_new = True

if create_new:
    print(f"Creating new index {INDEX_NAME} with {DIMENSIONS} dimensions...")
    pc.create_index(
        name=INDEX_NAME,
        dimension=DIMENSIONS,
        metric="cosine",
        spec=ServerlessSpec(cloud="aws", region="us-east-1")
    )
    # Wait for index to be ready
    while not pc.describe_index(INDEX_NAME).status['ready']:
        time.sleep(1)

index = pc.Index(INDEX_NAME)

# 2. Load Dataset
try:
    with open('dataset-template.json', 'r') as f:
        data = json.load(f)
except FileNotFoundError:
    print("Error: 'dataset-template.json' not found.")
    exit(1)

print(f"Embedding {len(data)} problems using {EMBEDDING_MODEL} (3072 dims)...")

for item in data:
    try:
        # 3. Generate Embedding
        # No 'output_dimensionality' needed; it defaults to 3072 natively
        embed_resp = genai_client.models.embed_content(
            model=EMBEDDING_MODEL,
            contents=item["problem"],
            config=types.EmbedContentConfig(
                task_type="RETRIEVAL_DOCUMENT",
                title=f"Math Problem {item['id']}"
            )
        )
        
        embedding = embed_resp.embeddings[0].values

        # 4. Upsert
        metadata = {
            "tags": item.get("tags", []), 
            "json": json.dumps(item)
        }

        index.upsert(vectors=[{
            "id": str(item["id"]), 
            "values": embedding, 
            "metadata": metadata
        }])
        print(f"✅ Uploaded Problem {item['id']}")
        
        time.sleep(0.1) # Rate limit safety

    except Exception as e:
        print(f"❌ Failed Problem {item.get('id', '?')}: {e}")

print("\nMigration Complete. Your database is now 3072-dimensional.")