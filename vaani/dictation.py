"""Hold-to-talk dictation for Windows.

  Hold  Right Ctrl  -> speak -> release : cleaned text is typed where your cursor is.
  Hold  Right Alt   -> speak an instruction -> release : rewrites the selected text
                       ("make this shorter", "isko proper English mein likho", "reply politely saying yes").
  Ctrl+Alt+Q        -> quit.

Keys are configurable in settings.json.
"""
from __future__ import annotations

import ctypes
import io
import sys
import threading
import time
import wave

from . import llm, stt
from .config import Dictionary, Settings

SAMPLE_RATE = 16000


# ---------------------------------------------------------------- audio

class Recorder:
    def __init__(self) -> None:
        import sounddevice as sd

        self._sd = sd
        self._frames: list[bytes] = []
        self._stream = None

    def start(self) -> None:
        self._frames = []
        self._stream = self._sd.RawInputStream(samplerate=SAMPLE_RATE, channels=1, dtype="int16",
                                               callback=lambda data, *_: self._frames.append(bytes(data)))
        self._stream.start()

    def stop(self) -> bytes:
        if self._stream:
            self._stream.stop()
            self._stream.close()
            self._stream = None
        buf = io.BytesIO()
        with wave.open(buf, "wb") as w:
            w.setnchannels(1)
            w.setsampwidth(2)
            w.setframerate(SAMPLE_RATE)
            w.writeframes(b"".join(self._frames))
        return buf.getvalue()

    def seconds(self) -> float:
        return sum(len(f) for f in self._frames) / 2 / SAMPLE_RATE


# ---------------------------------------------------------------- windows helpers

def active_app() -> str:
    """Title of the foreground window, e.g. 'Inbox - Gmail - Google Chrome'. Used to pick the tone."""
    try:
        user32 = ctypes.windll.user32
        hwnd = user32.GetForegroundWindow()
        n = user32.GetWindowTextLengthW(hwnd)
        buf = ctypes.create_unicode_buffer(n + 1)
        user32.GetWindowTextW(hwnd, buf, n + 1)
        return buf.value
    except Exception:
        return ""


def beep(kind: str) -> None:
    try:
        import winsound
        winsound.Beep({"start": 880, "stop": 660, "error": 220}[kind], 70)
    except Exception:
        pass


def paste(text: str) -> None:
    """Type text at the cursor via the clipboard (handles Hindi/Unicode), then restore the clipboard."""
    import keyboard
    import pyperclip

    try:
        old = pyperclip.paste()
    except Exception:
        old = None
    pyperclip.copy(text)
    time.sleep(0.05)
    keyboard.send("ctrl+v")
    time.sleep(0.25)
    if old is not None:
        pyperclip.copy(old)


def copy_selection() -> str:
    import keyboard
    import pyperclip

    sentinel = "\u0000vaani\u0000"
    try:
        old = pyperclip.paste()
    except Exception:
        old = ""
    pyperclip.copy(sentinel)
    keyboard.send("ctrl+c")
    time.sleep(0.2)
    sel = pyperclip.paste()
    pyperclip.copy(old)
    return "" if sel == sentinel else sel


# ---------------------------------------------------------------- the app

class App:
    def __init__(self) -> None:
        self.settings = Settings.load()
        self.dictionary = Dictionary.load()
        self.recorder = Recorder()
        self.mode: str | None = None  # "dictate" | "command"
        self.app_hint = ""
        self.lock = threading.Lock()

    def press(self, mode: str) -> None:
        with self.lock:
            if self.mode:  # already recording (key auto-repeat)
                return
            self.mode = mode
            self.app_hint = active_app()
            self.recorder.start()
            beep("start")

    def release(self, mode: str) -> None:
        with self.lock:
            if self.mode != mode:
                return
            audio = self.recorder.stop()
            secs = self.recorder.seconds()
            self.mode = None
        beep("stop")
        if secs < 0.3:
            return
        threading.Thread(target=self._process, args=(mode, audio, self.app_hint), daemon=True).start()

    def _process(self, mode: str, audio: bytes, app_hint: str) -> None:
        import tempfile
        from pathlib import Path

        try:
            # Copy the selection only after the hotkey is released, so Ctrl+C isn't mixed with it.
            selected = copy_selection() if mode == "command" else ""
            with tempfile.NamedTemporaryFile(suffix=".wav", delete=False) as f:
                f.write(audio)
                path = Path(f.name)
            try:
                raw = stt.transcribe(path, self.settings.stt_engine, prompt=self.dictionary.stt_hint(),
                                     model=self.settings.groq_model).text.strip()
            finally:
                path.unlink(missing_ok=True)
            if not raw:
                return
            print(f"  heard: {raw}")
            if mode == "command":
                text = llm.command(self.settings, selected, raw, app_hint)
            else:
                text = self.dictionary.exact_snippet(raw) or llm.dictation_cleanup(self.settings, raw, self.dictionary, app_hint)
            print(f"  typed: {text}")
            paste(text)
        except Exception as e:  # keep the app alive whatever happens
            beep("error")
            print(f"  error: {e}", file=sys.stderr)

    def run(self) -> None:
        import keyboard

        s = self.settings
        for key, mode in ((s.dictate_key, "dictate"), (s.command_key, "command")):
            keyboard.on_press_key(key, lambda e, m=mode: self.press(m), suppress=False)
            keyboard.on_release_key(key, lambda e, m=mode: self.release(m), suppress=False)
        print(f"Vaani is running.\n  Hold [{s.dictate_key}] to dictate."
              f"\n  Hold [{s.command_key}] to edit selected text by voice.\n  Ctrl+Alt+Q to quit.")
        keyboard.wait("ctrl+alt+q")


def main() -> int:
    if sys.platform != "win32":
        print("Dictation mode is for Windows. Transcription works everywhere: python -m vaani.transcribe <url-or-file>")
        return 1
    App().run()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
