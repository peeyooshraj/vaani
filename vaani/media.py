"""Get audio from a YouTube link or a local file and split it into chunks for speech-to-text."""
from __future__ import annotations

import re
import shutil
import subprocess
from pathlib import Path

from .stt import Segment, Transcript


def is_url(source: str) -> bool:
    return bool(re.match(r"https?://", source))


def download_audio(url: str, workdir: Path) -> tuple[Path, str]:
    """Download the best audio track with yt-dlp. Returns (file, video title)."""
    import yt_dlp

    workdir.mkdir(parents=True, exist_ok=True)
    opts = {"format": "bestaudio/best", "outtmpl": str(workdir / "source.%(ext)s"),
            "quiet": True, "noprogress": True, "noplaylist": True}
    with yt_dlp.YoutubeDL(opts) as ydl:
        info = ydl.extract_info(url, download=True)
        path = Path(ydl.prepare_filename(info))
    return path, info.get("title") or "youtube"


def _ffmpeg() -> str:
    exe = shutil.which("ffmpeg")
    if not exe:
        raise RuntimeError("ffmpeg is not installed. On Windows run:  winget install Gyan.FFmpeg")
    return exe


def split_audio(src: Path, workdir: Path, chunk_minutes: int = 10) -> list[tuple[Path, float]]:
    """Convert to 16 kHz mono MP3 and cut into chunks. Returns [(chunk, start_offset_seconds)]."""
    workdir.mkdir(parents=True, exist_ok=True)
    seconds = chunk_minutes * 60
    pattern = workdir / "chunk_%03d.mp3"
    subprocess.run([_ffmpeg(), "-y", "-loglevel", "error", "-i", str(src), "-vn", "-ac", "1", "-ar", "16000",
                    "-b:a", "48k", "-f", "segment", "-segment_time", str(seconds), "-reset_timestamps", "1",
                    str(pattern)], check=True)
    chunks = sorted(workdir.glob("chunk_*.mp3"))
    return [(c, i * seconds) for i, c in enumerate(chunks)]


def merge(parts: list[tuple[Transcript, float]]) -> Transcript:
    """Join chunk transcripts, shifting timestamps by each chunk's offset. Language = most common."""
    segs: list[Segment] = []
    langs: dict[str, float] = {}
    for t, offset in parts:
        dur = 0.0
        for s in t.segments:
            segs.append(Segment(s.start + offset, s.end + offset, s.text))
            dur += max(s.end - s.start, 0.1)
        langs[t.language] = langs.get(t.language, 0.0) + dur
    lang = max(langs, key=langs.get) if langs else "unknown"
    return Transcript(lang, segs)


def timestamp(sec: float) -> str:
    sec = int(sec)
    h, rem = divmod(sec, 3600)
    m, s = divmod(rem, 60)
    return f"{h:d}:{m:02d}:{s:02d}" if h else f"{m:02d}:{s:02d}"


def to_srt(t: Transcript) -> str:
    def ts(x: float) -> str:
        ms = int(round(x * 1000))
        h, ms = divmod(ms, 3_600_000)
        m, ms = divmod(ms, 60_000)
        s, ms = divmod(ms, 1000)
        return f"{h:02d}:{m:02d}:{s:02d},{ms:03d}"
    out = []
    for i, s in enumerate(t.segments, 1):
        out.append(f"{i}\n{ts(s.start)} --> {ts(s.end)}\n{s.text.strip()}\n")
    return "\n".join(out)


def chunk_text(text: str, max_words: int = 3500) -> list[str]:
    """Split long text on paragraph/sentence boundaries so each Claude call stays focused."""
    paras = [p for p in re.split(r"\n\s*\n", text) if p.strip()]
    if len(paras) <= 1:
        paras = re.split(r"(?<=[.?!।])\s+", text)
    out, cur, n = [], [], 0
    for p in paras:
        w = len(p.split())
        if cur and n + w > max_words:
            out.append("\n\n".join(cur))
            cur, n = [], 0
        cur.append(p)
        n += w
    if cur:
        out.append("\n\n".join(cur))
    return out
