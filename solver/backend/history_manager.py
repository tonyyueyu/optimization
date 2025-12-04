import json
import redis
import os
import uuid
from datetime import datetime
from typing import List, Dict, Optional, Any

# Connect to Redis
REDIS_HOST = os.getenv("REDIS_HOST", "localhost")
REDIS_PORT = int(os.getenv("REDIS_PORT", 6379))

try:
    r = redis.Redis(host=REDIS_HOST, port=REDIS_PORT, db=0, decode_responses=True)
    r.ping()
    print("✓ Redis connected successfully")
except Exception as e:
    print(f"Warning: Redis connection failed. History will not work. {e}")
    r = None

class HistoryManager:
    def __init__(self):
        self.redis = r
    
    def getUserHistoryKey(self, user_id: str) -> str:
        return f"chat_history:{user_id}"
    
    def getChatKey(self, chat_id: str) -> str:
        return f"chat:{chat_id}"
    
    def fetch_chat(self, chat_id: str) -> Optional[Dict[str, Any]]:
        if not self.redis:
            print("Redis not connected")
            return None

        key = self._get_chat_key(chat_id)
        value = self.redis.get(key)
        
        if not value:
            return None

        try:
            return json.loads(value)
        except json.JSONDecodeError:
            print(f"Warning: Chat {chat_id} is not valid JSON")
            return None
    
    def fetch_user_history(self, user_id: str) -> List[Dict[str, Any]]:
        if not self.redis:
            print("Redis not connected")
            return []

        key = self.getUserHistoryKey(user_id)

        chat_ids = self.redis.lrange(key, 0, -1)

        messages = []

        for chat_id in chat_ids:
            chat = self.fetch_chat(chat_id)
            if chat:
                messages.append(chat)
        
        return messages

    def save_message(self, user_id: str, message: Dict[str, Any]) -> str:
        if not self.redis:
            print("Redis not connected")
            return ""
        
        chat_id = f"{user_id}_{uuid.uuid4().hex[:8]}_{int(datetime.now().timestamp())}"

        message_with_meta = {
            **message,
            "chat_id": chat_id,
            "timestamp": datetime.now().isoformat(),
            "user_id": user_id
        }

        chat_key = self.getChatKey(chat_id)
        self.redis.set(chat_key, json.dumps(message_with_meta))

        history_key = self.getUserHistoryKey(user_id)
        self.redis.rpush(history_key, chat_id)

        return chat_id
    
    def save_conversation(self, user_id: str, user_message: Dict, assistant_message: Dict) -> tuple:
        if not self.redis:
            print("Redis not connected")
            return "", ""
        
        user_chat_id = self.save_message(user_id, {
            "role": "user",
            "content": user_message.get("content", ""),
            "type": "text"
        })
        
        assistant_chat_id = self.save_message(user_id, assistant_message)
        
        return user_chat_id, assistant_chat_id
    
    def clear_user_history(self, user_id: str) -> bool:
        if not self.redis:
            return False

        history_key = self.getUserHistoryKey(user_id)   
        
        chat_ids = self.redis.lrange(history_key, 0, -1)

        for chat_id in chat_ids:
            chat_key = self._get_chat_key(chat_id)
            self.redis.delete(chat_key)
        
        self.redis.delete(history_key)
        
        return True

        
