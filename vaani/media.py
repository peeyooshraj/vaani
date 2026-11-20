"""Get audio from a YouTube link or a local file and split it into chunks for speech-to-text."""
from __future__ import annotations

import re
import shutil
import subprocess
from pathlib import Path

from .stt import Segment, Transcript


def is_url(source: str) -> bool:
    return bool(re.match(r"https?://", source))


def video_title(url: str) -> str:
    """Read a video's title without downloading it."""
    import yt_dlp

    with yt_dlp.YoutubeDL({"quiet": True, "noplaylist": True, "socket_timeout": 30}) as ydl:
        info = ydl.extract_info(url, download=False) or {}
    return info.get("title") or "youtube"


def download_audio(url: str, workdir: Path) -> tuple[Path, str]:
    """Download the best audio track with yt-dlp. Returns (file, video title)."""
    import yt_dlp

    workdir.mkdir(parents=True, exist_ok=True)
    opts = {"format": "bestaudio/best", "outtmpl": str(workdir / "source.%(ext)s"),
            "quiet": True, "noprogress": True, "noplaylist": True, "socket_timeout": 30,
            "match_filter": yt_dlp.utils.match_filter_func("!is_live"),  # live streams never end
            "max_filesize": 2 * 1024**3}
    with yt_dlp.YoutubeDL(opts) as ydl:
        info = ydl.extract_info(url, download=True)
        if not info:
            raise RuntimeError(f"Could not read that link: {url}")
        done = info.get("requested_downloads") or []
        path = Path(done[0]["filepath"]) if done and done[0].get("filepath") else Path(ydl.prepare_filename(info))
    if not path.exists():
        raise RuntimeError("The download did not produce an audio file (live stream, private or too large?).")
    return path, info.get("title") or "youtube"


def _ffmpeg() -> str:
    exe = shutil.which("ffmpeg")
    if not exe:
        raise RuntimeError("ffmpeg is not installed. On Windows run:  winget install Gyan.FFmpeg")
    return exe


def _duration(path: Path) -> float | None:
    """Real length of a file in seconds (via ffprobe), or None if it can't be measured."""
    exe = shutil.which("ffprobe")
    if not exe:
        return None
    try:
        r = subprocess.run([exe, "-v", "error", "-show_entries", "format=duration",
                            "-of", "default=noprint_wrappers=1:nokey=1", str(path.resolve())],
                           capture_output=True, text=True, timeout=60, check=True)
        return float(r.stdout.strip())
    except (subprocess.SubprocessError, ValueError, OSError):
        return None


def split_audio(src: Path, workdir: Path, chunk_minutes: int = 10) -> list[tuple[Path, float]]:
    """Convert to 16 kHz mono MP3 and cut into chunks. Returns [(chunk, start_offset_seconds)]."""
    workdir.mkdir(parents=True, exist_ok=True)
    seconds = chunk_minutes * 60
    pattern = workdir / "chunk_%03d.mp3"
    # Absolute path: a file named "-something" can't be mistaken for an ffmpeg option.
    # Timeout: a corrupt file can't hang forever (an hour covers very long recordings).
    subprocess.run([_ffmpeg(), "-y", "-loglevel", "error", "-i", str(src.resolve()), "-vn", "-ac", "1",
                    "-ar", "16000", "-b:a", "48k", "-f", "segment", "-segment_time", str(seconds),
                    "-reset_timestamps", "1", str(pattern)], check=True, timeout=3600)
    chunks = sorted(workdir.glob("chunk_*.mp3"))
    # Add up each chunk's real length, so subtitles don't drift on long videos.
    out, offset = [], 0.0
    for c in chunks:
        out.append((c, offset))
        offset += _duration(c) or float(seconds)
    return out


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
        paras = [p for p in re.split(r"(?<=[.?!।])\s+", text) if p.strip()]
    units = []
    for p in paras:  # unpunctuated speech can be one giant "sentence": cut it by word count
        words = p.split()
        units += [" ".join(words[i:i + max_words]) for i in range(0, len(words), max_words)] \
            if len(words) > max_words else [p]
    out, cur, n = [], [], 0
    for p in units:
        w = len(p.split())
        if cur and n + w > max_words:
            out.append("\n\n".join(cur))
            cur, n = [], 0
        cur.append(p)
        n += w
    if cur:
        out.append("\n\n".join(cur))
    return out
