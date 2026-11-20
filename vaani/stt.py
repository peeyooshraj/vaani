"""Speech-to-text. Returns timestamped segments plus the detected language."""
from __future__ import annotations

import os
import threading
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
    language: str  # normalised 2-letter code, see language_code()
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


# Audio may be a file path or (filename, bytes) - dictation passes bytes so speech never touches the disk.
Audio = Path | tuple[str, bytes]


def transcribe(audio: Audio, engine: str = "groq", *, prompt: str = "", model: str = "whisper-large-v3",
               language: str | None = None) -> Transcript:
    name, data = (audio.name, audio.read_bytes()) if isinstance(audio, Path) else audio
    if engine == "groq":
        return _groq(name, data, prompt=prompt, model=model, language=language)
    if engine == "elevenlabs":
        return _elevenlabs(name, data, language=language)
    raise ValueError(f"Unknown speech engine: {engine}")


_groq_client = None
_groq_lock = threading.Lock()


def _groq_api():
    global _groq_client
    with _groq_lock:
        if _groq_client is None:
            from groq import Groq
            _groq_client = Groq()  # reads GROQ_API_KEY; retries 429/5xx by itself
        return _groq_client


def _groq(name: str, data: bytes, *, prompt: str, model: str, language: str | None) -> Transcript:
    kwargs = {}
    if prompt:
        kwargs["prompt"] = prompt
    if language:
        kwargs["language"] = language
    r = _groq_api().audio.transcriptions.create(
        model=model, file=(name, data), response_format="verbose_json",
        timestamp_granularities=["segment"], temperature=0.0, **kwargs,
    )
    body = r.model_dump() if hasattr(r, "model_dump") else dict(r)
    segs = [Segment(float(s["start"]), float(s["end"]), s["text"]) for s in (body.get("segments") or [])]
    if not segs and body.get("text"):
        segs = [Segment(0.0, 0.0, body["text"])]
    return Transcript(language_code(body.get("language")), segs)


def _elevenlabs(name: str, data: bytes, *, language: str | None) -> Transcript:
    key = os.environ.get("ELEVENLABS_API_KEY")
    if not key:
        raise RuntimeError("ELEVENLABS_API_KEY is not set (needed because stt_engine is 'elevenlabs').")
    form = {"model_id": "scribe_v1", "timestamps_granularity": "word"}
    if language:
        form["language_code"] = language
    r = requests.post("https://api.elevenlabs.io/v1/speech-to-text", headers={"xi-api-key": key},
                      data=form, files={"file": (name, data)}, timeout=600)
    r.raise_for_status()
    body = r.json()
    return Transcript(language_code(body.get("language_code")),
                      words_to_segments(body.get("words") or [], body.get("text", "")))


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
