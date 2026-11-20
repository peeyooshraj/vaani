import json
import subprocess
from pathlib import Path

from vaani import llm, media, stt, transcribe
from vaani.config import Dictionary


def test_merge_shifts_timestamps_and_picks_main_language():
    a = stt.Transcript("hi", [stt.Segment(0, 5, "namaste"), stt.Segment(5, 30, "aaj baat karte hain")])
    b = stt.Transcript("en", [stt.Segment(0, 2, "okay")])
    m = media.merge([(a, 0), (b, 600)])
    assert m.language == "hi"
    assert m.segments[-1].start == 600


def test_language_code():
    assert stt.language_code("Hindi") == "hi"
    assert stt.language_code("hin") == "hi"
    assert stt.language_code(None) == "unknown"


def test_words_to_segments():
    words = [{"text": "Hello", "start": 0, "end": 0.4}, {"text": " ", "type": "spacing"},
             {"text": "world.", "start": 0.5, "end": 0.9}, {"text": "Next", "start": 1.0, "end": 1.2}]
    segs = stt.words_to_segments(words)
    assert [s.text for s in segs] == ["Hello world.", "Next"]


def test_chunk_text_respects_limit():
    text = "\n\n".join(" ".join(["shabd"] * 100) for _ in range(10))
    chunks = media.chunk_text(text, max_words=250)
    assert len(chunks) == 5 and all(len(c.split()) <= 250 for c in chunks)


def test_snippet_exact_match():
    d = Dictionary(words=[], snippets={"my sign off": "Regards"})
    assert d.exact_snippet("My sign off.") == "Regards"
    assert d.exact_snippet("my sign off and more") is None


def test_srt():
    t = stt.Transcript("en", [stt.Segment(61.5, 63.25, "hi")])
    assert "00:01:01,500 --> 00:01:03,250" in media.to_srt(t)


def test_full_pipeline_hinglish(tmp_path, monkeypatch):
    """Real ffmpeg chunking; speech-to-text and Claude are faked."""
    audio = tmp_path / "talk.wav"
    subprocess.run(["ffmpeg", "-loglevel", "error", "-f", "lavfi", "-i", "sine=f=440:d=3", str(audio)], check=True)

    monkeypatch.setattr(stt, "transcribe", lambda *a, **k: stt.Transcript("hi", [stt.Segment(0, 3, "aaj hum baat karenge")]))
    calls = []

    def fake_ask(settings, system, user, *, effort, max_tokens=64000, json_schema=None):
        calls.append(system[0]["text"][:40])
        if json_schema:
            return json.dumps({"language": "hinglish", "language_name": "Hinglish", "transcript": "Aaj hum baat karenge."})
        return "Today we'll talk."

    monkeypatch.setattr(llm, "ask", fake_ask)
    out = transcribe.run(str(audio), out_dir=tmp_path / "out", hindi="hinglish-roman", log=lambda *_: None)
    assert (out / "transcript_hinglish.md").read_text(encoding="utf-8").count("Aaj hum baat karenge.") == 1
    assert "Today we'll talk." in (out / "english.md").read_text(encoding="utf-8")
    assert (out / "hindi_hinglish-roman.md").exists()
    assert (out / "subtitles_original.srt").exists()
    assert len(calls) == 3  # cleanup, English adaptation, Hindi adaptation
