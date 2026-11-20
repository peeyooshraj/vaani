"""Hold-to-talk dictation for Windows.

  Hold  Right Ctrl          -> speak -> release : cleaned text is typed where your cursor is.
  Hold  Shift + Right Ctrl  -> speak an instruction -> release : rewrites the selected text
                               ("make this shorter", "isko proper English mein likho", "reply politely saying yes").
  Ctrl+Alt+Q                -> quit.

Keys are configurable in settings.json.
"""
from __future__ import annotations

import ctypes
import io
import queue
import sys
import threading
import time
import uuid
import wave

from . import llm, stt
from .config import ConfigError, Dictionary, Settings, preflight

SAMPLE_RATE = 16000
MAX_RECORD_SECONDS = 120  # safety stop if a key-release is missed (e.g. a UAC prompt stole focus)


# ---------------------------------------------------------------- audio

class Recorder:
    def __init__(self) -> None:
        import sounddevice as sd

        self._sd = sd
        self._lock = threading.Lock()
        self._frames: list[bytes] = []
        self._bytes = 0
        self._stream = None

    def _callback(self, data, *_) -> None:
        with self._lock:
            room = SAMPLE_RATE * 2 * MAX_RECORD_SECONDS - self._bytes
            if room > 0:
                chunk = bytes(data)[:room]
                self._frames.append(chunk)
                self._bytes += len(chunk)

    def start(self) -> None:
        with self._lock:
            self._frames, self._bytes = [], 0
        stream = self._sd.RawInputStream(samplerate=SAMPLE_RATE, channels=1, dtype="int16", callback=self._callback)
        try:
            stream.start()
        except Exception:
            stream.close()
            raise
        self._stream = stream

    def stop(self) -> tuple[bytes, float]:
        """Returns (wav bytes, seconds recorded)."""
        stream, self._stream = self._stream, None
        if stream is not None:
            try:
                stream.stop()
            finally:
                stream.close()
        with self._lock:
            pcm, secs = b"".join(self._frames), self._bytes / 2 / SAMPLE_RATE
        buf = io.BytesIO()
        with wave.open(buf, "wb") as w:
            w.setnchannels(1)
            w.setsampwidth(2)
            w.setframerate(SAMPLE_RATE)
            w.writeframes(pcm)
        return buf.getvalue(), secs


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


def foreground_window() -> int:
    try:
        return int(ctypes.windll.user32.GetForegroundWindow())
    except Exception:
        return 0


def beep(kind: str) -> None:
    """Short status tone, played on its own thread so key handling never waits for it."""
    freq = {"start": 880, "stop": 660, "error": 220}.get(kind, 440)

    def play() -> None:
        try:
            import winsound
            winsound.Beep(freq, 70)
        except Exception:
            pass

    threading.Thread(target=play, daemon=True).start()


def _clip_get() -> str:
    import pyperclip
    try:
        return pyperclip.paste() or ""
    except Exception:
        return ""


def paste(text: str) -> None:
    """Type text at the cursor via the clipboard (handles Hindi/Unicode), then put the old text back.

    Limitation: only text is saved and restored. An image or copied file on the clipboard is replaced.
    """
    import keyboard
    import pyperclip

    old = _clip_get()
    pyperclip.copy(text)
    time.sleep(0.05)
    keyboard.send("ctrl+v")
    time.sleep(0.3)  # give the target app time to read the clipboard before we restore it
    if old:
        pyperclip.copy(old)


def copy_selection() -> str:
    """Return the selected text in the active app, or "" if nothing is selected."""
    import keyboard
    import pyperclip

    # A unique marker; if it is still on the clipboard after Ctrl+C, nothing was selected.
    # (No null characters: Windows would cut the text at the first one.)
    marker = f"__vaani_{uuid.uuid4().hex}__"
    old = _clip_get()
    pyperclip.copy(marker)
    time.sleep(0.03)
    keyboard.send("ctrl+c")
    time.sleep(0.2)
    sel = _clip_get()
    if old:
        pyperclip.copy(old)
    return "" if sel == marker else sel


# ---------------------------------------------------------------- the app

class App:
    def __init__(self) -> None:
        self.settings = Settings.load()
        self.dictionary = Dictionary.load()
        preflight(self.settings)
        self.recorder = Recorder()
        self.mode: str | None = None  # "dictate" | "command" while a key is held
        self.app_hint = ""
        self.window = 0
        self.lock = threading.Lock()
        self.watchdog: threading.Timer | None = None
        # One worker handles recordings strictly in order, so two quick dictations never
        # fight over the clipboard or get pasted out of order.
        self.jobs: queue.Queue = queue.Queue()
        threading.Thread(target=self._worker, daemon=True).start()

    def press(self, key_mode: str) -> None:
        import keyboard

        with self.lock:
            if self.mode:  # already recording (key auto-repeat)
                return
            mode = "command" if key_mode == "command" or keyboard.is_pressed("shift") else "dictate"
            try:
                self.recorder.start()
            except Exception as e:  # mic unplugged / busy / blocked: report it, stay usable
                beep("error")
                print(f"  microphone error: {e}", file=sys.stderr)
                return
            self.mode = mode
            self.app_hint = active_app()
            self.window = foreground_window()
            self.watchdog = threading.Timer(MAX_RECORD_SECONDS, self.finish)
            self.watchdog.daemon = True
            self.watchdog.start()
        beep("start")

    def finish(self) -> None:
        """Called on key release, or by the watchdog if the release was never seen."""
        with self.lock:
            if not self.mode:
                return
            mode, self.mode = self.mode, None
            if self.watchdog:
                self.watchdog.cancel()
            try:
                audio, secs = self.recorder.stop()
            except Exception as e:
                beep("error")
                print(f"  microphone error: {e}", file=sys.stderr)
                return
            app_hint, window = self.app_hint, self.window
        beep("stop")
        if secs >= 0.3:
            self.jobs.put((mode, audio, app_hint, window))

    def _worker(self) -> None:
        while True:
            job = self.jobs.get()
            if job is None:
                return
            try:
                self._process(*job)
            except Exception as e:  # keep the app alive whatever happens
                beep("error")
                print(f"  error: {e}", file=sys.stderr)

    def _process(self, mode: str, audio: bytes, app_hint: str, window: int) -> None:
        # Copy the selection only now (keys released), so Ctrl+C isn't mixed with the held hotkey.
        selected = copy_selection() if mode == "command" else ""
        raw = stt.transcribe(("speech.wav", audio), self.settings.stt_engine,
                             prompt=self.dictionary.stt_hint(), model=self.settings.groq_model).text.strip()
        if not raw:
            return
        print(f"  heard: {raw}")
        if mode == "command":
            text = llm.command(self.settings, selected, raw, app_hint)
        else:
            text = self.dictionary.exact_snippet(raw) or llm.dictation_cleanup(
                self.settings, raw, self.dictionary, app_hint)
        if not text:
            return
        if foreground_window() != window:
            # You switched windows while it was working: don't paste into the wrong place.
            import pyperclip
            pyperclip.copy(text)
            beep("error")
            print("  window changed - text is on the clipboard instead; press Ctrl+V where you want it.")
            return
        print(f"  typed: {text}")
        paste(text)

    def run(self) -> None:
        import keyboard

        s = self.settings
        keys = [(s.dictate_key, "dictate")] + ([(s.command_key, "command")] if s.command_key else [])
        for key, mode in keys:
            keyboard.on_press_key(key, lambda e, m=mode: self.press(m), suppress=False)
            keyboard.on_release_key(key, lambda e: self.finish(), suppress=False)
        cmd = s.command_key or f"shift + {s.dictate_key}"
        print(f"Vaani is running.\n  Hold [{s.dictate_key}] to dictate.\n"
              f"  Hold [{cmd}] to edit selected text by voice.\n  Ctrl+Alt+Q to quit.\n"
              "  (Typing into apps opened 'as administrator' needs Vaani started as administrator too.)")
        try:
            keyboard.wait("ctrl+alt+q")
        finally:
            keyboard.unhook_all()
            self.jobs.put(None)


def main() -> int:
    if sys.platform != "win32":
        print("Dictation mode is for Windows. Transcription works everywhere: python -m vaani.transcribe <url-or-file>")
        return 1
    try:
        App().run()
    except ConfigError as e:
        print(e, file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
