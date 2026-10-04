from __future__ import annotations

import re
from dataclasses import dataclass
from pathlib import Path

from ..llm import Gemini
from ..sources import SourceInfo


@dataclass
class Ctx:
    root: Path               # dataset root
    gemini: Gemini | None    # None = never use a model


ADMONITION = re.compile(r"^(WARNING|CAUTION)\b", re.I)
NOTE = re.compile(r"^Note\b[^:]{0,40}:", re.I)


def admonition_of(text: str) -> str | None:
    if ADMONITION.match(text):
        return "warning"
    if NOTE.match(text):
        return "note"
    return None


def clean(s: str | None) -> str:
    return re.sub(r"[ \t\u00a0]+", " ", (s or "").replace("\r", "")).strip()
