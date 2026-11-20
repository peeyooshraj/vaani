"""Settings and the personal dictionary.

API keys come from environment variables (never stored in these files):
  ANTHROPIC_API_KEY   - Claude, for cleanup / adaptation / command mode
  GROQ_API_KEY        - speech-to-text with Whisper large-v3 (default engine)
  ELEVENLABS_API_KEY  - optional speech-to-text with ElevenLabs Scribe
"""
from __future__ import annotations

import json
import os
import shutil
from dataclasses import asdict, dataclass, field
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
PROMPTS = ROOT / "prompts"
SETTINGS_FILE = ROOT / "settings.json"
DICTIONARY_FILE = ROOT / "dictionary.json"

VALID_STT_ENGINES = {"groq", "elevenlabs"}
VALID_DICTATION_OUTPUTS = {"as_spoken", "english", "hindi"}
VALID_HINGLISH_SCRIPTS = {"roman", "devanagari"}
VALID_EFFORTS = {"low", "medium", "high", "xhigh", "max"}
STT_KEY_VARS = {"groq": "GROQ_API_KEY", "elevenlabs": "ELEVENLABS_API_KEY"}


class ConfigError(ValueError):
    pass


@dataclass
class Settings:
    # Claude model for transcripts (quality matters most here).
    model: str = "claude-opus-5-5"
    # Claude model for live dictation and command mode. Set e.g. "claude-haiku-5-5" for faster typing.
    dictation_model: str = "claude-opus-5-5"
    dictation_effort: str = "low"
    adaptation_effort: str = "high"

    # Speech-to-text engine: "groq" (Whisper large-v3) or "elevenlabs" (Scribe).
    stt_engine: str = "groq"
    groq_model: str = "whisper-large-v3"

    # Dictation output: "as_spoken" (Hinglish stays Hinglish), "english", or "hindi".
    dictation_output: str = "as_spoken"
    # How Hinglish is written when kept: "roman" (Aaj meeting hai) or "devanagari".
    hinglish_script: str = "roman"

    # Hold-to-talk key. Hold Shift as well for command mode.
    # (Right Alt is avoided: on Indian/international layouts it is AltGr = Ctrl+Alt.)
    dictate_key: str = "right ctrl"
    # Optional separate key for command mode, e.g. "f9". Empty = use Shift + dictate_key.
    command_key: str = ""

    # Media transcription: minutes per audio chunk sent to speech-to-text (1..30, keeps files small).
    chunk_minutes: int = 10

    def validate(self) -> None:
        def check(name: str, value, allowed) -> None:
            if value not in allowed:
                raise ConfigError(f"settings.json: {name} is {value!r}; use one of {sorted(allowed)}")

        check("stt_engine", self.stt_engine, VALID_STT_ENGINES)
        check("dictation_output", self.dictation_output, VALID_DICTATION_OUTPUTS)
        check("hinglish_script", self.hinglish_script, VALID_HINGLISH_SCRIPTS)
        check("dictation_effort", self.dictation_effort, VALID_EFFORTS)
        check("adaptation_effort", self.adaptation_effort, VALID_EFFORTS)
        if isinstance(self.chunk_minutes, bool) or not isinstance(self.chunk_minutes, int) \
                or not 1 <= self.chunk_minutes <= 30:
            raise ConfigError(f"settings.json: chunk_minutes is {self.chunk_minutes!r}; use a whole number from 1 to 30")
        if not self.dictate_key:
            raise ConfigError("settings.json: dictate_key is empty")

    @classmethod
    def load(cls, path: Path = SETTINGS_FILE) -> "Settings":
        s = cls()
        data = _read_json(path)
        if data is not None:
            for k, v in data.items():
                if hasattr(s, k):
                    setattr(s, k, v)
        s.validate()
        return s

    def save(self, path: Path = SETTINGS_FILE) -> None:
        self.validate()
        path.write_text(json.dumps(asdict(self), indent=2), encoding="utf-8")


@dataclass
class Dictionary:
    """Words the speech engine often gets wrong, plus voice snippets."""
    words: list[str] = field(default_factory=list)
    snippets: dict[str, str] = field(default_factory=dict)

    @classmethod
    def load(cls, path: Path = DICTIONARY_FILE) -> "Dictionary":
        data = _read_json(path)
        if data is None:
            return cls()
        words, snippets = data.get("words", []), data.get("snippets", {})
        if not isinstance(words, list) or not isinstance(snippets, dict):
            raise ConfigError(f"{path.name}: 'words' must be a list and 'snippets' an object")
        return cls(words=[str(w) for w in words], snippets={str(k): str(v) for k, v in snippets.items()})

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


def _read_json(path: Path) -> dict | None:
    if not path.exists():
        return None
    try:
        data = json.loads(path.read_text(encoding="utf-8-sig"))  # -sig: tolerate Notepad's BOM
    except json.JSONDecodeError as e:
        raise ConfigError(f"{path.name} has a typo at line {e.lineno}, column {e.colno}: {e.msg}") from e
    if not isinstance(data, dict):
        raise ConfigError(f"{path.name} must contain a JSON object {{ ... }}")
    return data


def _norm(s: str) -> str:
    return "".join(ch for ch in s.lower() if ch.isalnum() or ch.isspace()).strip()


def load_prompt(name: str) -> str:
    path = PROMPTS / name
    if not path.exists():
        raise ConfigError(f"Prompt file missing: {path}")
    return path.read_text(encoding="utf-8")


def preflight(settings: Settings, *, needs_ffmpeg: bool = False, prompts: tuple[str, ...] = ()) -> None:
    """Check keys, tools and files before any paid work starts. Raises ConfigError listing every problem."""
    problems = []
    for var in ("ANTHROPIC_API_KEY", STT_KEY_VARS[settings.stt_engine]):
        if not os.environ.get(var):
            problems.append(f"{var} is not set (see README: setx {var} \"...\", then open a new window)")
    if needs_ffmpeg and not shutil.which("ffmpeg"):
        problems.append("ffmpeg is not installed (run: winget install Gyan.FFmpeg, then open a new window)")
    for p in prompts:
        if not (PROMPTS / p).exists():
            problems.append(f"prompt file missing: prompts/{p}")
    if problems:
        raise ConfigError("Can't start yet:\n  - " + "\n  - ".join(problems))
