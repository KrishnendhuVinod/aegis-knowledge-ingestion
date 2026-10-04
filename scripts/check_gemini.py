"""Verify your Gemini key + model BEFORE running ingestion.

    python scripts/check_gemini.py

Lists the models your key can call (free-tier availability differs per account and
changes over time) and makes one tiny test call with GEMINI_MODEL. If the default
model is unavailable, copy a name from the printed list into .env as GEMINI_MODEL.
"""
import os
import sys

from dotenv import load_dotenv

load_dotenv()
key = os.getenv("GEMINI_API_KEY") or os.getenv("GOOGLE_API_KEY")
if not key:
    sys.exit("No GEMINI_API_KEY found. Create one at https://aistudio.google.com/apikey and put it in .env")

from google import genai  # noqa: E402

client = genai.Client(api_key=key)
print("Models that support generateContent for this key:")
for m in client.models.list():
    if "generateContent" in (getattr(m, "supported_actions", None) or []):
        print("  ", m.name.replace("models/", ""))

model = os.getenv("GEMINI_MODEL", "gemini-3.1-flash-lite")
print(f"\nTest call with {model} ...")
r = client.models.generate_content(model=model, contents="Reply with the single word: ok")
print("response:", r.text.strip())
