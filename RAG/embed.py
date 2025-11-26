import ollama
import numpy as np
import pinecone

PINECONE_API_KEY = "pcsk_bpvp5_KwTepQWna8UPTFAzZCkCTSQqMnLUNwtwCh3nhm1Rx2ogExfb5BpHQLGCVKYf4Bz"
PINECONE_ENV = "us-west1-gcp"

pinecone.init(api_key=PINECONE_API_KEY, environment=PINECONE_ENV)

index_name = "math-questions"
if index_name not in pinecone.list_indexes():
    pinecone.create_index(index_name, dimension=1024)
index = pinecone.Index(index_name)


EMBEDDING_MODEL = 'hf.co/CompendiumLabs/bge-base-en-v1.5-gguf'

def make_embedding(chunk, chunk_id):
    embed = ollama.embed(model = EMBEDDING_MODEL, input = chunk)['embeddings'][0]
    index.upsert([(chunk_id, embed, {"text": chunk})])

def retrive_questions(query, top_n = 2):
    query_embed = ollama.embed(model = EMBEDDING_MODEL, input = query)['embeddings'][0]
    
    results = index.query(vector=query_embed, top_k=top_n, include_metadata=True)

    top_chunks = []

    #Process each result based on input structure
