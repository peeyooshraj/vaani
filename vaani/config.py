"""Settings and the personal dictionary.

API keys come from environment variables (never stored in these files):
  ANTHROPIC_API_KEY   - Claude, for cleanup / adaptation / command mode
  GROQ_API_KEY        - speech-to-text with Whisper large-v3 (default engine)
  ELEVENLABS_API_KEY  - optional speech-to-text with ElevenLabs Scribe
"""
from __future__ import annotations

import json
from dataclasses import dataclass, field, asdict
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
PROMPTS = ROOT / "prompts"
SETTINGS_FILE = ROOT / "settings.json"
DICTIONARY_FILE = ROOT / "dictionary.json"


@dataclass
class Settings:
    # Claude model used for every text step. Change here if you want a cheaper one.
    model: str = "claude-opus-5-5"
    # Effort for quick dictation cleanup vs. long transcript adaptation.
    dictation_effort: str = "low"
    adaptation_effort: str = "high"

    # Speech-to-text engine: "groq" (Whisper large-v3) or "elevenlabs" (Scribe).
    stt_engine: str = "groq"
    groq_model: str = "whisper-large-v3"

    # Dictation output: "as_spoken" (Hinglish stays Hinglish), "english", or "hindi".
    dictation_output: str = "as_spoken"
    # How Hinglish is written when kept: "roman" (Aaj meeting hai) or "devanagari".
    hinglish_script: str = "roman"

    # Hold-to-talk keys (names as understood by the `keyboard` library).
    dictate_key: str = "right ctrl"
    command_key: str = "right alt"

    # Media transcription: length of each audio chunk sent to speech-to-text.
    chunk_minutes: int = 10

    @classmethod
    def load(cls, path: Path = SETTINGS_FILE) -> "Settings":
        s = cls()
        if path.exists():
            data = json.loads(path.read_text(encoding="utf-8"))
            for k, v in data.items():
                if hasattr(s, k):
                    setattr(s, k, v)
        return s

    def save(self, path: Path = SETTINGS_FILE) -> None:
        path.write_text(json.dumps(asdict(self), indent=2), encoding="utf-8")


@dataclass
class Dictionary:
    """Words the speech engine often gets wrong, plus voice snippets."""
    words: list[str] = field(default_factory=list)
    snippets: dict[str, str] = field(default_factory=dict)

    @classmethod
    def load(cls, path: Path = DICTIONARY_FILE) -> "Dictionary":
        if not path.exists():
            return cls()
        data = json.loads(path.read_text(encoding="utf-8"))
        return cls(words=list(data.get("words", [])), snippets=dict(data.get("snippets", {})))

    def stt_hint(self) -> str:
        """Short vocabulary hint for Whisper's `prompt` (it only reads ~224 tokens)."""
        return ", ".join(self.words)[:600]

    def exact_snippet(self, text: str) -> str | None:
        """If the whole utterance is a snippet trigger, return its expansion."""
        key = _norm(text)
        for trigger, expansion in self.snippets.items():
            if _norm(trigger) == key:
                return expansion
        return None


def _norm(s: str) -> str:
    return "".join(ch for ch in s.lower() if ch.isalnum() or ch.isspace()).strip()


def load_prompt(name: str) -> str:
    return (PROMPTS / name).read_text(encoding="utf-8")
