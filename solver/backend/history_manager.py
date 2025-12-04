import json
import redis
import os

# Connect to Redis
# If you are using Docker for Redis, host might be 'redis' instead of 'localhost'
REDIS_HOST = os.getenv("localhost")
try:
    r = redis.Redis(host=REDIS_HOST, port=6379, db=0, decode_responses=True)
except Exception as e:
    print(f"Warning: Redis connection failed. History will not work. {e}")
    r = None

class HistoryManager:
    def __init__(self):
        self.redis = r

    def get_history(self, session_id: str):
        """
        Retrieves list of messages from Redis and converts them 
        into the format Gemini expects (list of dicts).
        """
        if not self.redis: return []
        
        raw_data = self.redis.get(f"chat:{session_id}")
        if raw_data:
            return json.loads(raw_data)
        return []

    def save_history(self, session_id: str, chat_session):
        """
        Extracts history from the Gemini ChatSession object 
        and saves it to Redis.
        """
        if not self.redis: return

        # Gemini history is a list of complex objects. We need to serialize them.
        # Format: [{'role': 'user', 'parts': ['text...']}, {'role': 'model', ...}]
        serializable_history = []
        
        for message in chat_session.history:
            # message.parts is usually a list, we grab the text
            part_text = message.parts[0].text if message.parts else ""
            serializable_history.append({
                "role": message.role,
                "parts": [part_text]
            })

        # Save to Redis (Expire in 24 hours to keep memory clean)
        self.redis.setex(
            f"chat:{session_id}", 
            86400, 
            json.dumps(serializable_history)
        )