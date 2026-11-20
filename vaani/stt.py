"""Speech-to-text. Returns timestamped segments plus the detected language."""
from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path

import requests


@dataclass
class Segment:
    start: float  # seconds
    end: float
    text: str


@dataclass
class Transcript:
    language: str  # e.g. "hindi", "english", "hi", "en" - normalised by language_code()
    segments: list[Segment]

    @property
    def text(self) -> str:
        return " ".join(s.text.strip() for s in self.segments if s.text.strip())


def language_code(lang: str | None) -> str:
    """Groq returns names ("hindi"), ElevenLabs returns codes ("hin"). Normalise to 2 letters."""
    if not lang:
        return "unknown"
    lang = lang.lower().strip()
    names = {"hindi": "hi", "english": "en", "urdu": "ur", "hin": "hi", "eng": "en", "urd": "ur",
             "marathi": "mr", "bengali": "bn", "tamil": "ta", "telugu": "te", "gujarati": "gu",
             "punjabi": "pa", "kannada": "kn", "malayalam": "ml", "spanish": "es", "french": "fr",
             "german": "de", "japanese": "ja", "chinese": "zh", "arabic": "ar", "russian": "ru"}
    return names.get(lang, lang[:2])


def transcribe(path: Path, engine: str = "groq", *, prompt: str = "", model: str = "whisper-large-v3",
               language: str | None = None) -> Transcript:
    if engine == "groq":
        return _groq(path, prompt=prompt, model=model, language=language)
    if engine == "elevenlabs":
        return _elevenlabs(path, language=language)
    raise ValueError(f"Unknown speech engine: {engine}")


def _groq(path: Path, *, prompt: str, model: str, language: str | None) -> Transcript:
    from groq import Groq

    client = Groq()  # reads GROQ_API_KEY
    kwargs = {}
    if prompt:
        kwargs["prompt"] = prompt
    if language:
        kwargs["language"] = language
    with open(path, "rb") as f:
        r = client.audio.transcriptions.create(
            model=model, file=(path.name, f.read()), response_format="verbose_json",
            timestamp_granularities=["segment"], temperature=0.0, **kwargs,
        )
    data = r.model_dump() if hasattr(r, "model_dump") else dict(r)
    segs = [Segment(float(s["start"]), float(s["end"]), s["text"]) for s in (data.get("segments") or [])]
    if not segs and data.get("text"):
        segs = [Segment(0.0, 0.0, data["text"])]
    return Transcript(language_code(data.get("language")), segs)


def _elevenlabs(path: Path, *, language: str | None) -> Transcript:
    key = os.environ["ELEVENLABS_API_KEY"]
    data = {"model_id": "scribe_v1", "timestamps_granularity": "word"}
    if language:
        data["language_code"] = language
    with open(path, "rb") as f:
        r = requests.post("https://api.elevenlabs.io/v1/speech-to-text",
                          headers={"xi-api-key": key}, data=data, files={"file": (path.name, f)}, timeout=600)
    r.raise_for_status()
    body = r.json()
    return Transcript(language_code(body.get("language_code")), words_to_segments(body.get("words") or [], body.get("text", "")))


def words_to_segments(words: list[dict], fallback_text: str = "", max_len: float = 12.0) -> list[Segment]:
    """Group word timestamps into ~sentence-sized segments."""
    segs: list[Segment] = []
    cur: list[str] = []
    start = None
    end = 0.0
    for w in words:
        if w.get("type", "word") == "spacing":
            continue
        t = w.get("text", "")
        if start is None:
            start = float(w.get("start", 0.0))
        end = float(w.get("end", start))
        cur.append(t)
        if t.rstrip().endswith((".", "?", "!", "।")) or end - start >= max_len:
            segs.append(Segment(start, end, " ".join(cur)))
            cur, start = [], None
    if cur:
        segs.append(Segment(start or 0.0, end, " ".join(cur)))
    if not segs and fallback_text:
        segs = [Segment(0.0, 0.0, fallback_text)]
    return segs
