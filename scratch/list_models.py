from google import genai
import os
import json

# Read api key from settings
settings_file = 'data/settings.json'
if os.path.exists(settings_file):
    with open(settings_file, 'r', encoding='utf-8') as f:
        settings = json.load(f)
else:
    settings = {}

api_key = settings.get("gemini_api_key")
if not api_key:
    print("No API key found in settings.")
    exit(1)

# Initialize the new genai Client
client = genai.Client(api_key=api_key)

print("Listing all models available for your API key:")
try:
    models = client.models.list()
    for m in models:
        print(f"Model: {m.name} | Supported Actions: {m.supported_stage if hasattr(m, 'supported_stage') else ''}")
except Exception as e:
    print("Failed to list models:", str(e))
