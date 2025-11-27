import ollama
import numpy as np
import pinecone
import json

PINECONE_API_KEY = "pcsk_bpvp5_KwTepQWna8UPTFAzZCkCTSQqMnLUNwtwCh3nhm1Rx2ogExfb5BpHQLGCVKYf4Bz"
PINECONE_ENV = "us-west1-gcp"

pinecone.init(api_key=PINECONE_API_KEY, environment=PINECONE_ENV)

index_name = "math-questions"
if index_name not in pinecone.list_indexes():
    pinecone.create_index(index_name, dimension=1024)
index = pinecone.Index(index_name)


EMBEDDING_MODEL = 'hf.co/CompendiumLabs/bge-base-en-v1.5-gguf'

def store_problem(json_obj):
    problem_id = str(json_obj['id'])

    embed = ollama.embed( model=EMBEDDING_MODEL, input=json_obj["problem"] )["embeddings"][0]

    index.upsert([(problem_id, embed, {"json": json.dumps(json_obj)})])

    print(f"Stored problem {problem_id}")

