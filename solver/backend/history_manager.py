import os
import uuid
from datetime import datetime
from typing import Dict, List, Any, Optional

import firebase_admin
from firebase_admin import credentials, db
from dotenv import load_dotenv

load_dotenv()

# -------------------- Firebase Initialization --------------------

def init_firebase():
    """Initializes the Firebase Admin SDK using credentials from environment variables."""
    if firebase_admin._apps:
        return


    cred_dict = {
        "type": os.getenv("FIREBASE_TYPE"),
        "project_id": os.getenv("FIREBASE_PROJECT_ID"),
        "private_key_id": os.getenv("FIREBASE_PRIVATE_KEY_ID"),
        "private_key": os.getenv("FIREBASE_PRIVATE_KEY").replace("\\n", "\n"),
        "client_email": os.getenv("FIREBASE_CLIENT_EMAIL"),
        "client_id": os.getenv("FIREBASE_CLIENT_ID"),
        "auth_uri": os.getenv("FIREBASE_AUTH_URI"),
        "token_uri": os.getenv("FIREBASE_TOKEN_URI"),
        "auth_provider_x509_cert_url": os.getenv("FIREBASE_AUTH_PROVIDER_X509_CERT_URL"),
        "client_x509_cert_url": os.getenv("FIREBASE_CLIENT_X509_CERT_URL"),
        "universe_domain": os.getenv("FIREBASE_UNIVERSE_DOMAIN"),
    }

    cred = credentials.Certificate(cred_dict)
    firebase_admin.initialize_app(cred, {"databaseURL": os.getenv("FIREBASE_DB_URL")})

init_firebase()


class HistoryManager:
    """
    Manages a nested Firebase structure:
    Users -> Chat Sessions -> Messages
    """

    def __init__(self):
        self.root = db.reference("chat_history")

    def _user_ref(self, user_id: str):
        return self.root.child(user_id)

    def create_chat_session(self, user_id: str, title: str = "New Chat") -> str:
        """Creates a new chat session container and returns the session_id."""
        session_id = f"session_{uuid.uuid4().hex[:12]}"
        session_ref = self._user_ref(user_id).child(session_id)
        
        session_ref.child("metadata").set({
            "title": title,
            "created_at": datetime.utcnow().isoformat(),
            "last_updated": datetime.utcnow().isoformat()
        })
        return session_id

    def add_message(self, user_id: str, session_id: str, role: str, content: str):
        """Adds a message to a specific chat session."""
        session_ref = self._user_ref(user_id).child(session_id)
        
        message_data = {
            "role": role, 
            "content": content,
            "timestamp": datetime.utcnow().isoformat()
        }
        
        session_ref.child("messages").push(message_data)
        
        session_ref.child("metadata").update({
            "last_updated": datetime.utcnow().isoformat()
        })

    def fetch_user_sessions(self, user_id: str) -> Dict[str, Any]:
        """Fetches all chat sessions for a user (metadata only)."""
        data = self._user_ref(user_id).get()
        if not data:
            return {}
        
        return {sid: content.get("metadata") for sid, content in data.items()}

    def fetch_session_messages(self, user_id: str, session_id: str) -> List[Dict[str, Any]]:
        """Fetches all messages within a specific session, sorted by time."""
        data = self._user_ref(user_id).child(session_id).child("messages").get()
        
        if not data:
            return []

        messages = list(data.values())
        messages.sort(key=lambda x: x.get("timestamp", ""))
        return messages

    def delete_session(self, user_id: str, session_id: str):
        """Deletes a specific chat session."""
        self._user_ref(user_id).child(session_id).delete()

    def clear_all_history(self, user_id: str):
        """Deletes everything for a user."""
        self._user_ref(user_id).delete()

    def truncate_session(self, user_id: str, session_id: str, index: int):
        """
        Deletes all messages from a specific index onwards.
        If index is 2, it keeps messages 0 and 1, and deletes 2, 3, 4...
        """
        messages_ref = self._user_ref(user_id).child(session_id).child("messages")
        data = messages_ref.get()
        
        if not data:
            return

        # Firebase returns a dict, we need to sort keys by the timestamp inside the values
        # or by the push-ID (which is chronological)
        sorted_keys = sorted(data.keys(), key=lambda k: data[k].get("timestamp", ""))
        
        keys_to_delete = sorted_keys[index:]
        
        for key in keys_to_delete:
            messages_ref.child(key).delete()
            
        # Update metadata
        self._user_ref(user_id).child(session_id).child("metadata").update({
            "last_updated": datetime.utcnow().isoformat()
        })