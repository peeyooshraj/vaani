"""Transcribe a YouTube video or audio/video file, then adapt it.

Language rules:
  * English audio                -> clean English transcript.
  * Hindi / Hinglish audio       -> transcript in that language (as spoken)  +  proper English adaptation.
  * Any other language           -> transcript in that language              +  proper English adaptation.
  * --hindi                      -> additionally adapt the result into Hindi/Hinglish with the master prompt.

If a run stops halfway (internet drop, closed window), run the same command again:
finished steps are reused instead of being paid for twice. Use --fresh to start over.

Usage:
  python -m vaani.transcribe "https://www.youtube.com/watch?v=..."
  python -m vaani.transcribe "C:\\path\\to\\talk.mp3" --hindi hinglish-roman
"""
from __future__ import annotations

import argparse
import json
import re
import sys
import tempfile
from datetime import datetime
from pathlib import Path

from . import llm, media, stt
from .config import ROOT, ConfigError, Dictionary, Settings, preflight

_RESERVED = {"CON", "PRN", "AUX", "NUL", *(f"COM{i}" for i in range(1, 10)), *(f"LPT{i}" for i in range(1, 10))}
STATE = ".vaani_state.json"


class NoSpeechError(RuntimeError):
    pass


def run(source: str, out_dir: Path | None = None, hindi: str | None = None, context: str = "",
        language: str | None = None, fresh: bool = False, log=print) -> Path:
    settings, dictionary = Settings.load(), Dictionary.load()
    prompts = ("english_adaptation.md",) + (("hindi_adaptation.md",) if hindi else ())
    preflight(settings, needs_ffmpeg=True, prompts=prompts)  # fail before any download or paid call

    is_url = media.is_url(source)
    if not is_url and not Path(source).exists():
        raise FileNotFoundError(f"File not found: {source}")
    title = media.video_title(source) if is_url else Path(source).stem
    out = _output_folder(source, title, out_dir, fresh)
    state = _load_state(out)
    if state.get("source") not in (None, source):
        raise ConfigError(f"{out} holds a transcript of a different source; choose another --out folder.")
    state.update(source=source, title=title)

    # Stage 1: speech-to-text
    if "raw" in state:
        log("Reusing saved speech-to-text.")
        raw = stt.Transcript(state["raw"]["language"],
                             [stt.Segment(*seg) for seg in state["raw"]["segments"]])
    else:
        raw = _speech_to_text(source, is_url, settings, dictionary, language, log)
        if not raw.text.strip():
            raise NoSpeechError("No speech was found in this audio.")
        state["raw"] = {"language": raw.language, "segments": [[s.start, s.end, s.text] for s in raw.segments]}
        _save_state(out, state)
        (out / "raw_timestamped.txt").write_text(
            "\n".join(f"[{media.timestamp(s.start)}] {s.text.strip()}" for s in raw.segments), encoding="utf-8")
        (out / "subtitles_original.srt").write_text(media.to_srt(raw), encoding="utf-8")

    # Stage 2: faithful cleanup in the spoken language
    if "clean" not in state:
        log("Cleaning transcript...")
        parts, lang, lang_name = [], None, None
        for piece in media.chunk_text(raw.text):
            r = llm.clean_transcript(settings, piece, raw.language, dictionary)
            lang, lang_name = lang or r["language"], lang_name or r["language_name"]
            parts.append(r["transcript"])
        state["clean"] = {"language": lang, "language_name": lang_name, "text": "\n\n".join(parts)}
        _save_state(out, state)
        (out / f"transcript_{lang}.md").write_text(
            f"# {title}\n\nLanguage: {lang_name}\n\n{state['clean']['text']}\n", encoding="utf-8")
    lang, lang_name, transcript = (state["clean"][k] for k in ("language", "language_name", "text"))

    # Stage 3: proper English
    if lang == "english":
        english = transcript
    else:
        if "english" not in state:
            log(f"Adapting {lang_name} into proper English...")
            state["english"] = "\n\n".join(llm.adapt_to_english(settings, p, lang_name, context)
                                           for p in media.chunk_text(transcript, 6000))
            _save_state(out, state)
            (out / "english.md").write_text(f"# {title} (English)\n\n{state['english']}\n", encoding="utf-8")
        english = state["english"]

    # Stage 4 (optional): Hindi / Hinglish with the master prompt.
    # Rebuilt from the English meaning on purpose: the master prompt is an English-to-Hindi engine, and
    # going through meaning gives polished narration instead of a re-spelled transcript.
    if hindi:
        key = f"hindi_{hindi}"
        if key not in state:
            log("Adapting into Hindi/Hinglish...")
            state[key] = "\n\n".join(llm.adapt_to_hindi(settings, p, hindi, context)
                                     for p in media.chunk_text(english, 6000))
            _save_state(out, state)
            (out / f"{key}.md").write_text(f"# {title} (Hindi)\n\n{state[key]}\n", encoding="utf-8")

    log(f"Done. Files are in: {out}")
    return out


def _speech_to_text(source, is_url, settings, dictionary, language, log) -> stt.Transcript:
    with tempfile.TemporaryDirectory(prefix="vaani_") as tmp:
        tmpdir = Path(tmp)
        if is_url:
            log("Downloading audio...")
            audio, _ = media.download_audio(source, tmpdir)
        else:
            audio = Path(source)
        log("Preparing audio...")
        chunks = media.split_audio(audio, tmpdir / "chunks", settings.chunk_minutes)
        parts = []
        for i, (chunk, offset) in enumerate(chunks, 1):
            log(f"Speech-to-text {i}/{len(chunks)}...")
            parts.append((stt.transcribe(chunk, settings.stt_engine, prompt=dictionary.stt_hint(),
                                         model=settings.groq_model, language=language), offset))
        return media.merge(parts)


def _output_folder(source: str, title: str, out_dir: Path | None, fresh: bool) -> Path:
    """Same source again -> same folder (resume). A different file with the same name -> a new folder."""
    if out_dir is None:
        base = ROOT / "transcripts" / _safe(title)
        prev = _load_state(base).get("source") if base.exists() else None
        if base.exists() and (fresh or prev != source):
            base = base.with_name(f"{base.name}_{datetime.now():%Y%m%d_%H%M%S}")
        out_dir = base
    elif fresh and (out_dir / STATE).exists():
        (out_dir / STATE).unlink()
    out_dir.mkdir(parents=True, exist_ok=True)
    return out_dir


def _load_state(folder: Path) -> dict:
    f = folder / STATE
    try:
        return json.loads(f.read_text(encoding="utf-8")) if f.exists() else {}
    except json.JSONDecodeError:
        return {}  # a half-written state file just means "start over"


def _save_state(folder: Path, state: dict) -> None:
    tmp = folder / (STATE + ".tmp")
    tmp.write_text(json.dumps(state, ensure_ascii=False), encoding="utf-8")
    tmp.replace(folder / STATE)  # atomic, so a crash never leaves a broken file


def _safe(name: str) -> str:
    cleaned = re.sub(r'[<>:"/\\|?*\x00-\x1f]+', "_", name).strip(" .")[:80] or "transcript"
    # Windows refuses folders called CON, NUL, COM1... (also with an extension, e.g. "con.txt").
    return f"_{cleaned}" if cleaned.split(".")[0].upper() in _RESERVED else cleaned


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(description="Transcribe and adapt a YouTube video or audio file.")
    p.add_argument("source", help="YouTube URL or path to an audio/video file")
    p.add_argument("--out", type=Path, help="output folder (default: transcripts/<title>)")
    p.add_argument("--hindi", choices=["devanagari", "hinglish-devanagari", "hinglish-roman"],
                   help="also produce a Hindi/Hinglish adaptation using the master prompt")
    p.add_argument("--context", default="", help="who is speaking / what it is about (improves accuracy)")
    p.add_argument("--language", help="force the spoken language code, e.g. hi or en (default: auto)")
    p.add_argument("--fresh", action="store_true", help="ignore saved progress and start again")
    a = p.parse_args(argv)
    try:
        run(a.source, a.out, a.hindi, a.context, a.language, a.fresh)
    except llm.RefusedError as e:
        print(f"Claude declined: {e}", file=sys.stderr)
        return 2
    except (ConfigError, NoSpeechError, FileNotFoundError) as e:
        print(e, file=sys.stderr)
        return 1
    except Exception as e:
        print(f"Stopped: {e}\nRun the same command again to continue from where it stopped.", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
