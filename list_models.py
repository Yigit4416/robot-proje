import os
from google import genai
from dotenv import load_dotenv

load_dotenv()

api_key = os.getenv("GOOGLE_API_KEY") or os.getenv("GEMINI_API_KEY")
client = genai.Client(api_key=api_key)

print("Available models:")
try:
    for model in client.models.list():
        # Using getattr to be safe since SDK versions vary
        name = getattr(model, 'name', 'Unknown')
        actions = getattr(model, 'supported_actions', 'Unknown')
        print(f"- {name} (Actions: {actions})")
except Exception as e:
    print(f"Error listing models: {e}")
