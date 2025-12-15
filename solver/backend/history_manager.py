import os
import uuid
from datetime import datetime
from typing import Dict, List, Any, Optional

from dotenv import load_dotenv
import firebase_admin
from firebase_admin import credentials, db

load_dotenv()

# -------------------- Firebase Initialization --------------------

def init_firebase():
    """
    Initialize Firebase using env vars.
    This runs once per process.
    """
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

    firebase_admin.initialize_app(
        cred,
        {"databaseURL": os.getenv("FIREBASE_DB_URL")}
    )


init_firebase()


# -------------------- History Manager --------------------

class HistoryManager:
    """
    Firebase structure:

    /chat_history
        /{user_id}
            /{chat_id}
                chat_id
                user_id
                message
                timestamp
    """

    def __init__(self):
        self.root = db.reference("chat_history")

    def _user_ref(self, user_id: str):
        return self.root.child(user_id)


    def fetch_user_history(self, user_id: str) -> List[Dict[str, Any]]:
        """
        Get all chat messages for a user.
        """
        data = self._user_ref(user_id).get()

        if not data:
            return []

        messages = list(data.values())

        messages.sort(key=lambda x: x.get("timestamp", ""))

        return messages

    def save_message(self, user_id: str, message: Dict[str, Any]) -> str:
        """
        Save a single chat message.
        """
        chat_id = f"{user_id}_{uuid.uuid4().hex[:8]}"

        payload = {
            **message,
            "chat_id": chat_id,
            "user_id": user_id,
            "timestamp": datetime.utcnow().isoformat()
        }

        self._user_ref(user_id).child(chat_id).set(payload)

        return chat_id

    def fetch_chat(self, user_id: str, chat_id: str) -> Optional[Dict[str, Any]]:
        """
        Fetch a single chat by ID.
        """
        return self._user_ref(user_id).child(chat_id).get()

    def clear_user_history(self, user_id: str) -> bool:
        """
        Delete all chat history for a user.
        """
        self._user_ref(user_id).delete()
        return True
