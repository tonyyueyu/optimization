import google.generativeai as genai
import os

# Ensure your key is set in the terminal: export GOOGLE_API_KEY="AIza..."
genai.configure(api_key='AIzaSyDkb9Fi5TtRPpcODlmyafaBK4tdQFT5gpo')

print("Available Models:")
for m in genai.list_models():
    # Only show models that generate content (chat/text)
    if 'generateContent' in m.supported_generation_methods:
        print(f"- {m.name}")