"""Transcribe a YouTube video or audio/video file, then adapt it.

Language rules:
  * English audio                -> clean English transcript.
  * Hindi / Hinglish audio       -> transcript in that language (as spoken)  +  proper English adaptation.
  * Any other language           -> transcript in that language              +  proper English adaptation.
  * --hindi                      -> additionally adapt the result into Hindi/Hinglish with the master prompt.

Usage:
  python -m vaani.transcribe "https://www.youtube.com/watch?v=..."
  python -m vaani.transcribe "C:\\path\\to\\talk.mp3" --hindi hinglish-roman
"""
from __future__ import annotations

import argparse
import re
import sys
import tempfile
from pathlib import Path

from . import llm, media, stt
from .config import ROOT, Dictionary, Settings


def run(source: str, out_dir: Path | None = None, hindi: str | None = None, context: str = "",
        language: str | None = None, log=print) -> Path:
    settings, dictionary = Settings.load(), Dictionary.load()

    with tempfile.TemporaryDirectory(prefix="vaani_") as tmp:
        tmpdir = Path(tmp)
        if media.is_url(source):
            log("Downloading audio...")
            audio, title = media.download_audio(source, tmpdir)
        else:
            audio, title = Path(source), Path(source).stem
            if not audio.exists():
                raise FileNotFoundError(audio)

        out = out_dir or (ROOT / "transcripts" / _safe(title))
        out.mkdir(parents=True, exist_ok=True)

        log("Preparing audio...")
        chunks = media.split_audio(audio, tmpdir / "chunks", settings.chunk_minutes)
        parts = []
        for i, (chunk, offset) in enumerate(chunks, 1):
            log(f"Speech-to-text {i}/{len(chunks)}...")
            parts.append((stt.transcribe(chunk, settings.stt_engine, prompt=dictionary.stt_hint(),
                                         model=settings.groq_model, language=language), offset))
        raw = media.merge(parts)

    (out / "raw_timestamped.txt").write_text(
        "\n".join(f"[{media.timestamp(s.start)}] {s.text.strip()}" for s in raw.segments), encoding="utf-8")
    (out / "subtitles_original.srt").write_text(media.to_srt(raw), encoding="utf-8")

    log("Cleaning transcript...")
    cleaned_parts, lang, lang_name = [], None, None
    for piece in media.chunk_text(raw.text):
        r = llm.clean_transcript(settings, piece, raw.language, dictionary)
        lang = lang or r["language"]
        lang_name = lang_name or r["language_name"]
        cleaned_parts.append(r["transcript"])
    transcript = "\n\n".join(cleaned_parts)
    (out / f"transcript_{lang}.md").write_text(f"# {title}\n\nLanguage: {lang_name}\n\n{transcript}\n", encoding="utf-8")

    if lang == "english":
        english = transcript
    else:
        log(f"Adapting {lang_name} into proper English...")
        english = "\n\n".join(llm.adapt_to_english(settings, p, lang_name, context)
                              for p in media.chunk_text(transcript, 6000))
        (out / "english.md").write_text(f"# {title} (English)\n\n{english}\n", encoding="utf-8")

    if hindi:
        log("Adapting into Hindi/Hinglish...")
        # Always adapt from the English text, so the Hindi is rebuilt from meaning, not re-spelled.
        hi = "\n\n".join(llm.adapt_to_hindi(settings, p, hindi, context) for p in media.chunk_text(english, 6000))
        (out / f"hindi_{hindi}.md").write_text(f"# {title} (Hindi)\n\n{hi}\n", encoding="utf-8")

    log(f"Done. Files are in: {out}")
    return out


def _safe(name: str) -> str:
    return re.sub(r'[<>:"/\\|?*\x00-\x1f]+', "_", name).strip(" .")[:80] or "transcript"


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(description="Transcribe and adapt a YouTube video or audio file.")
    p.add_argument("source", help="YouTube URL or path to an audio/video file")
    p.add_argument("--out", type=Path, help="output folder (default: transcripts/<title>)")
    p.add_argument("--hindi", choices=["devanagari", "hinglish-devanagari", "hinglish-roman"],
                   help="also produce a Hindi/Hinglish adaptation using the master prompt")
    p.add_argument("--context", default="", help="who is speaking / what it is about (improves accuracy)")
    p.add_argument("--language", help="force the spoken language code, e.g. hi or en (default: auto)")
    a = p.parse_args(argv)
    try:
        run(a.source, a.out, a.hindi, a.context, a.language)
    except llm.RefusedError as e:
        print(f"Claude declined: {e}", file=sys.stderr)
        return 2
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
