from google import genai
from dotenv import load_dotenv
import os

load_dotenv()
import asyncio
import httpx
from google import genai
from google.genai import types

API_KEY = os.getenv("GOOGLE_API_KEY")

async def test():
    # Patch httpx first
    original_init = httpx.AsyncClient.__init__
    def patched_init(self, *args, **kwargs):
        kwargs['timeout'] = httpx.Timeout(600.0, read=600.0)
        print(f"DEBUG: AsyncClient created with timeout: {kwargs['timeout']}")
        return original_init(self, *args, **kwargs)
    httpx.AsyncClient.__init__ = patched_init
    
    client = genai.Client(
        api_key=API_KEY,
        http_options={'timeout': 600}
    )
    
    print("Testing gemini-3-flash-preview with streaming...")
    
    chat = client.aio.chats.create(
        model="gemini-3-flash-preview",
        history=[],
        config=types.GenerateContentConfig(temperature=0.1)
    )
    
    try:
        stream = await chat.send_message_stream("What is 2+2? Reply in one word.")
        async for chunk in stream:
            print(f"CHUNK: {chunk.text}")
    except httpx.ReadTimeout as e:
        print(f"TIMEOUT: {e}")
    except Exception as e:
        print(f"ERROR: {type(e).__name__}: {e}")

asyncio.run(test())