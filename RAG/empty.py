import os
from pinecone import Pinecone
from dotenv import load_dotenv

# Load API Keys
load_dotenv()
PINECONE_API_KEY = os.getenv("PINECONE_API_KEY")

# --- CONFIGURATION ---
INDEX_NAME = "math-questions"

# Initialize Pinecone Client
pc = Pinecone(api_key=PINECONE_API_KEY)

# Check if index exists and wipe it
existing_indexes = [i.name for i in pc.list_indexes()]

if INDEX_NAME in existing_indexes:
    print(f"Connecting to index '{INDEX_NAME}'...")
    index = pc.Index(INDEX_NAME)
    
    print("Wiping all data from the default namespace...")
    # This deletes all vectors but keeps the index alive
    index.delete(delete_all=True)
    
    print("✅ Database successfully wiped.")
    
    # NOTE: If you wanted to completely destroy the index instead of just emptying it, 
    # you would use this line instead:
    # pc.delete_index(INDEX_NAME)
else:
    print(f"⚠️ Index '{INDEX_NAME}' does not exist.")