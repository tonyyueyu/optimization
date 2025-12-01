import ollama
import numpy as np
from pinecone import Pinecone, ServerlessSpec
import json

PINECONE_API_KEY = "pcsk_bpvp5_KwTepQWna8UPTFAzZCkCTSQqMnLUNwtwCh3nhm1Rx2ogExfb5BpHQLGCVKYf4Bz"
PINECONE_ENV = "us-west1-gcp"
index_name = "math-questions"
DIMENSIONS = 768
EMBEDDING_MODEL = 'hf.co/CompendiumLabs/bge-base-en-v1.5-gguf'

pc = Pinecone(api_key=PINECONE_API_KEY)

if index_name not in [i.name for i in pc.list_indexes()]:
    pc.create_index(
        name=index_name,
        dimension=DIMENSIONS,
        metric="cosine",
        spec=ServerlessSpec(cloud="aws", region="us-east-1") 
    )

index = pc.Index(index_name)

with open('dataset.json', 'r') as f:
    data = json.load(f)

print(f"Uploading {len(data)} problems...")

for item in data:
    # Generate embedding
    response = ollama.embed(model=EMBEDDING_MODEL, input=item["problem"])
    embedding = response["embeddings"][0]

    # Upsert to Pinecone
    index.upsert(vectors=[{
        "id": str(item["id"]), 
        "values": embedding, 
        "metadata": {"json": json.dumps(item)}
    }])
    print(f"Uploaded {item['id']}")