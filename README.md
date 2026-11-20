# Vaani: voice typing and transcripts for Windows

Vaani does two jobs:

1. **Transcribe**: give it a YouTube link or an audio/video file and it writes the transcript.
   - English audio: a clean English transcript.
   - Hindi or Hinglish audio: the transcript exactly as spoken (Hindi in Devanagari, Hinglish kept mixed),
     **plus** a natural English version that adapts the meaning instead of translating word for word.
   - Any other language: the transcript in that language, plus natural English.
   - Optional `--hindi`: also rebuilds the content in Hindi or Hinglish using the master adaptation prompt
     (`prompts/hindi_adaptation.md`).
2. **Dictate**: hold a key, speak, let go. The cleaned text appears wherever your cursor is (any app).
   - **AI cleanup** removes fillers and applies "no wait, I mean…" corrections and punctuation.
     The tone fits the app you're typing in.
   - **Hindi/Hinglish**: speak in either. You get the output mode you set (as spoken, English, or Hindi).
   - **Command mode**: select text, hold the command key and say what to do
     ("make it shorter", "isko polite English mein likho"). The selection is replaced.
   - **Dictionary and snippets**: in `dictionary.json`, list words it keeps misspelling and phrases
     that expand ("my sign off" turns into your full signature).

## One-time setup (Windows)

1. Install **Python 3.11+** from python.org (tick "Add to PATH").
2. Install **ffmpeg**: open PowerShell and run `winget install Gyan.FFmpeg`.
3. Get two API keys:
   - Claude: https://console.anthropic.com (does the cleanup and the language adaptation)
   - Groq: https://console.groq.com (fast Whisper speech-to-text; very cheap)
4. Save them (PowerShell, then open a new window):
   ```
   setx ANTHROPIC_API_KEY "sk-ant-..."
   setx GROQ_API_KEY "gsk_..."
   ```

## Use it

- **Transcribe**: double-click `transcribe.bat`, paste a YouTube link (or drag in a file) and press Enter.
  The results go to `transcripts\<title>\`:
  `transcript_<language>.md`, `english.md`, `raw_timestamped.txt`, `subtitles_original.srt`.
  From a terminal you have more options:
  ```
  .venv\Scripts\python -m vaani.transcribe "https://youtu.be/..." --hindi hinglish-roman --context "Ramayana explainer"
  ```
- **Dictate**: double-click `start_dictation.bat` and leave the window open.
  - Hold **Right Ctrl** and speak to type.
  - Hold **Right Alt** and speak to edit the selected text.
  - **Ctrl+Alt+Q** quits.

The first run of either `.bat` file installs everything into `.venv` by itself.

## Settings (`settings.json`)

| Setting | Options |
|---|---|
| `dictation_output` | `as_spoken` (default), `english`, `hindi` |
| `hinglish_script` | `roman` (Aaj meeting hai) or `devanagari` |
| `dictate_key`, `command_key` | any key name, e.g. `right ctrl`, `f9`, `caps lock` |
| `stt_engine` | `groq` (default) or `elevenlabs` (set `ELEVENLABS_API_KEY`; often better on heavy Hinglish) |
| `model` | Claude model for text steps (default `claude-opus-5-5`) |

## How it works

```
mic / YouTube / file
   -> ffmpeg (16 kHz mono, 10-minute chunks)
   -> Whisper large-v3 (speech to text + timestamps)
   -> Claude: faithful cleanup in the spoken language
   -> Claude: meaning-first adaptation into English (prompts/english_adaptation.md)
              and, if asked, into Hindi/Hinglish (prompts/hindi_adaptation.md)
   -> files, or pasted at your cursor
```

Long system prompts are prompt-cached, so repeat calls cost less.
