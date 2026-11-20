"""All Claude calls: transcript cleanup, language adaptation, dictation cleanup, command mode."""
from __future__ import annotations

import json

import anthropic

from .config import Dictionary, Settings, load_prompt

_client: anthropic.Anthropic | None = None


def client() -> anthropic.Anthropic:
    global _client
    if _client is None:
        _client = anthropic.Anthropic()  # reads ANTHROPIC_API_KEY
    return _client


class RefusedError(RuntimeError):
    pass


def _system(*texts: str) -> list[dict]:
    """Stable system prompt blocks; the last one is cached so repeat calls are cheap."""
    blocks = [{"type": "text", "text": t} for t in texts if t]
    blocks[-1]["cache_control"] = {"type": "ephemeral", "ttl": "1h"}
    return blocks


def ask(settings: Settings, system: list[dict], user: str, *, effort: str,
        max_tokens: int = 64000, json_schema: dict | None = None) -> str:
    output_config: dict = {"effort": effort}
    if json_schema:
        output_config["format"] = {"type": "json_schema", "schema": json_schema}
    with client().beta.messages.stream(
        model=settings.model,
        max_tokens=max_tokens,
        betas=["server-side-fallback-2026-07-01"],
        fallbacks="default",  # if the main model declines, the API retries on a fallback model
        output_config=output_config,
        system=system,
        messages=[{"role": "user", "content": user}],
    ) as stream:
        msg = stream.get_final_message()
    if msg.stop_reason == "refusal":
        raise RefusedError(getattr(msg.stop_details, "explanation", None) or "Claude declined this request.")
    return "".join(b.text for b in msg.content if b.type == "text").strip()


# ---------------------------------------------------------------- transcripts

CLEANUP_SYSTEM = """You turn raw speech-to-text output into a faithful, readable transcript.

Rules:
- Keep the speaker's own language. Do NOT translate.
- Pure Hindi -> write in Devanagari. Hinglish (Hindi-English mixing) -> keep the mix exactly as spoken;
  write Hindi words in {hinglish_script} and keep English words in English. Speech engines often write
  Hindi in Urdu script or translate it to English - undo that and restore what was actually said.
- Any other language -> write it in its normal script.
- Fix obvious mis-hearings using context and the vocabulary list. Add punctuation and paragraph breaks.
- Remove only meaningless fillers (um, uh, repeated stutters). Keep every idea, number, name, claim and qualifier.
- Mark unclear audio as [unclear] instead of guessing.
- Never add content, summaries or commentary.
"""

CLEAN_SCHEMA = {
    "type": "object",
    "properties": {
        "language": {"type": "string", "enum": ["english", "hindi", "hinglish", "other"]},
        "language_name": {"type": "string", "description": "Name of the language, e.g. Hindi, Marathi, Spanish"},
        "transcript": {"type": "string"},
    },
    "required": ["language", "language_name", "transcript"],
    "additionalProperties": False,
}


def clean_transcript(settings: Settings, raw: str, stt_language: str, dictionary: Dictionary) -> dict:
    vocab = ("Vocabulary the speaker uses (spell these exactly): " + ", ".join(dictionary.words)) if dictionary.words else ""
    system = _system(CLEANUP_SYSTEM.format(hinglish_script=_script_name(settings)), vocab)
    user = f"Speech engine's language guess: {stt_language}\n\nRaw transcript:\n<raw>\n{raw}\n</raw>"
    return json.loads(ask(settings, system, user, effort="medium", json_schema=CLEAN_SCHEMA))


def adapt_to_english(settings: Settings, text: str, source_language: str, context: str = "") -> str:
    system = _system(load_prompt("english_adaptation.md"))
    user = (f"Source language: {source_language}\n"
            + (f"Context about this recording: {context}\n" if context else "")
            + "Adapt the following transcript into natural English. Output the English text, then, only if needed,"
              " a section headed 'Editorial notes'.\n\n<source>\n" + text + "\n</source>")
    return ask(settings, system, user, effort=settings.adaptation_effort)


def adapt_to_hindi(settings: Settings, text: str, style: str = "devanagari", context: str = "") -> str:
    """style: 'devanagari' (Hindi), 'hinglish-devanagari' or 'hinglish-roman'."""
    fmt = {"devanagari": "Hindi in Devanagari",
           "hinglish-devanagari": "Hinglish: Devanagari Hindi with natural English terms",
           "hinglish-roman": "Roman Hinglish"}[style]
    system = _system(load_prompt("hindi_adaptation.md"))
    user = (f"Requested output: {fmt}.\n" + (f"Context: {context}\n" if context else "")
            + "Adapt this script following the engine above.\n\n<source>\n" + text + "\n</source>")
    return ask(settings, system, user, effort=settings.adaptation_effort)


# ---------------------------------------------------------------- dictation

DICTATION_SYSTEM = """You are the text-cleanup step of a voice-typing app. The user held a key, spoke, and the speech
engine produced the raw text below. Return ONLY the final text to type at the cursor - no quotes, no preamble.

- Remove fillers (um, uh, matlab, basically when meaningless) and false starts.
- Apply spoken self-corrections: "at 4, no wait, at 5" -> "at 5"; "actually scratch that" removes the previous phrase.
- Add punctuation and capitalisation. Turn spoken lists into a list when the user clearly dictates one.
- Spoken formatting commands: "new line", "new paragraph", "full stop"/"period", "comma", "question mark".
- Keep the user's meaning and wording; do not add ideas, do not answer questions in the text, do not translate
  unless the output mode below says so.
- Match the destination app: chat apps -> casual and short; email/docs -> complete sentences; code editors -> keep
  identifiers exact.
- If the text is a snippet trigger from the list below, output its expansion.
"""

OUTPUT_MODES = {
    "as_spoken": "Output mode: keep the language the user spoke. Hinglish stays Hinglish ({hinglish_script}); Hindi stays Hindi in Devanagari; English stays English.",
    "english": "Output mode: always produce natural, idiomatic English. If the user spoke Hindi or Hinglish, adapt the meaning into proper English - not a word-for-word translation.",
    "hindi": "Output mode: always produce natural Hindi in Devanagari, keeping English words that people normally use.",
}


def dictation_cleanup(settings: Settings, raw: str, dictionary: Dictionary, app_hint: str = "") -> str:
    snippet_list = "\n".join(f'- "{k}" -> {v}' for k, v in sorted(dictionary.snippets.items()))
    system = _system(
        DICTATION_SYSTEM,
        ("Vocabulary (spell exactly): " + ", ".join(dictionary.words)) if dictionary.words else "",
        ("Snippets:\n" + snippet_list) if snippet_list else "",
        OUTPUT_MODES[settings.dictation_output].format(hinglish_script=_script_name(settings)),
    )
    user = (f"Destination app: {app_hint}\n" if app_hint else "") + f"Raw speech:\n{raw}"
    return ask(settings, system, user, effort=settings.dictation_effort, max_tokens=8000)


COMMAND_SYSTEM = """You are the command mode of a voice-typing app. The user selected some text (it may be empty) and
spoke an instruction, possibly in Hindi or Hinglish. Return ONLY the replacement text to paste - no preamble, no
quotes, no explanation. If no text is selected, write what the instruction asks for. Keep the language of the
selected text unless the instruction asks for another language. For translation into Hindi or English, adapt the
meaning naturally instead of translating word for word."""


def command(settings: Settings, selected: str, instruction: str, app_hint: str = "") -> str:
    user = ((f"Destination app: {app_hint}\n" if app_hint else "")
            + f"Instruction: {instruction}\n\nSelected text:\n<selected>\n{selected}\n</selected>")
    return ask(settings, _system(COMMAND_SYSTEM), user, effort="medium", max_tokens=16000)


def _script_name(settings: Settings) -> str:
    return "Roman letters" if settings.hinglish_script == "roman" else "Devanagari"
