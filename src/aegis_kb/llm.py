"""Thin Gemini wrapper with an on-disk response cache.

Why the cache matters (this is a design decision, not a convenience):
  * Free-tier quotas are small and change; a cache means each image is read once.
  * Model output is non-deterministic. The cache pins what the pipeline saw, so
    the evaluation numbers in the report can be reproduced by anyone WITHOUT a key.
  * Commit data/cache/ to git. The assessor can run everything offline.

If there is no key and no cache entry, `generate_json` returns None and callers
fall back to OCR-only. The pipeline never crashes because the LLM is missing.
"""
from __future__ import annotations

import hashlib
import json
import os
import re
import time
from pathlib import Path

DEFAULT_MODEL = "gemini-3.1-flash-lite"   # override with GEMINI_MODEL; verify with scripts/check_gemini.py


class Gemini:
    def __init__(self, cache_dir: Path, model: str | None = None, api_key: str | None = None):
        self.cache_dir = Path(cache_dir)
        self.cache_dir.mkdir(parents=True, exist_ok=True)
        self.model = model or os.getenv("GEMINI_MODEL", DEFAULT_MODEL)
        self.api_key = api_key or os.getenv("GEMINI_API_KEY") or os.getenv("GOOGLE_API_KEY")
        self._client = None
        self.stats = {"cache_hits": 0, "api_calls": 0, "skipped_no_key": 0}

    @property
    def can_call_api(self) -> bool:
        return bool(self.api_key)

    def _key(self, prompt: str, image: bytes | None) -> str:
        h = hashlib.sha256()
        h.update(self.model.encode())
        h.update(prompt.encode())
        if image:
            h.update(image)
        return h.hexdigest()

    def _client_lazy(self):
        if self._client is None:
            from google import genai
            self._client = genai.Client(api_key=self.api_key)
        return self._client

    def generate_json(self, prompt: str, image: bytes | None = None,
                      mime: str = "image/png", retries: int = 5) -> dict | None:
        key = self._key(prompt, image)
        cache_file = self.cache_dir / f"{key}.json"
        if cache_file.exists():
            self.stats["cache_hits"] += 1
            return json.loads(cache_file.read_text(encoding="utf-8"))["response"]
        if not self.can_call_api:
            self.stats["skipped_no_key"] += 1
            return None

        from google.genai import types
        contents = []
        if image:
            contents.append(types.Part.from_bytes(data=image, mime_type=mime))
        contents.append(prompt)
        config = types.GenerateContentConfig(response_mime_type="application/json", temperature=0)

        delay = 4.0
        for attempt in range(retries):
            try:
                resp = self._client_lazy().models.generate_content(
                    model=self.model, contents=contents, config=config)
                self.stats["api_calls"] += 1
                parsed = _parse_json(resp.text)
                cache_file.write_text(json.dumps(
                    {"model": self.model, "prompt": prompt, "response": parsed},
                    ensure_ascii=False, indent=2), encoding="utf-8")
                return parsed
            except Exception as e:  # 429 / 503 are routine on the free tier
                msg = str(e)
                transient = any(t in msg for t in ("429", "503", "RESOURCE_EXHAUSTED", "UNAVAILABLE"))
                if not transient or attempt == retries - 1:
                    raise
                time.sleep(delay)
                delay *= 2
        return None


def _parse_json(text: str) -> dict:
    text = re.sub(r"^```(?:json)?|```$", "", (text or "").strip(), flags=re.M).strip()
    return json.loads(text)
