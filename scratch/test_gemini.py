from google import genai
from google.genai import types
from PIL import Image
import io
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

# Initialize the new genai Client with explicit v1 version
client = genai.Client(api_key=api_key, http_options={'api_version': 'v1'})

# Create a tiny 1x1 pixel image in memory
img = Image.new('RGB', (100, 100), color = 'red')
img_byte_arr = io.BytesIO()
img.save(img_byte_arr, format='JPEG')
img_bytes = img_byte_arr.getvalue()

print("Testing generate_content (OCR simulation) using Client.models.generate_content...")
try:
    response = client.models.generate_content(
        model="gemini-1.5-flash",
        contents=[
            types.Part.from_bytes(
                data=img_bytes,
                mime_type='image/jpeg',
            ),
            "What is the color of this image? Reply in Arabic."
        ]
    )
    print("Generate Content Success:", response.text)
except Exception as e:
    print("Generate Content Failed:", str(e))

print("\nTesting single text embedding...")
try:
    response = client.models.embed_content(
        model="text-embedding-004",
        contents="اختبار التضمين"
    )
    # The response is of type EmbedContentResponse
    print("Single Embedding Success. Vector length:", len(response.embeddings[0].values))
except Exception as e:
    print("Single Embedding Failed:", str(e))

print("\nTesting batch text embedding...")
try:
    response = client.models.embed_content(
        model="text-embedding-004",
        contents=["اختبار التضمين الأول", "اختبار التضمين الثاني"]
    )
    print("Batch Embedding Success. Count:", len(response.embeddings))
    print("First Vector length:", len(response.embeddings[0].values))
except Exception as e:
    print("Batch Embedding Failed:", str(e))
