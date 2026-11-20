# Vaani: the complete guide

How to use it, why it exists, how it works, where it fails, and how it could get better.

---

## 1. What it is, in one picture

```
                         ┌──────────────────────── VAANI ────────────────────────┐
                         │                                                        │
  YOUR VOICE ──(hold key)─┼─► record ─► Whisper ─► Claude cleanup ─► typed at cursor
                         │              (speech    (fillers, fixes,                 │
                         │               to text)   tone, language)                 │
                         │                                                        │
  YOUTUBE LINK ──────────┼─► download ─► ffmpeg ─► Whisper ─► Claude ─► files       │
  or AUDIO FILE          │               (chunks)            │                     │
                         │                                   ├─ transcript (as spoken)
                         │                                   ├─ proper English
                         │                                   └─ Hindi/Hinglish (optional)
                         └────────────────────────────────────────────────────────┘
```

There are two tools in one:

| Tool | You do | You get |
|---|---|---|
| **Dictation** | Hold Right Ctrl, speak, release | Clean text typed in any app (WhatsApp Web, Gmail, Word, Notepad…) |
| **Command mode** | Select text, hold Shift + Right Ctrl, say an instruction | The selected text rewritten ("make it polite", "isko English mein") |
| **Transcription** | Give a YouTube link or audio/video file | Transcript, proper English, subtitles, optional Hindi/Hinglish script |

---

## 2. Why use it (what problem it solves)

- **Typing is slower than talking.** Speaking runs at about 150 words a minute; most people type 40.
- **Ordinary voice typing fails on Hinglish.** Windows and Google voice typing force you to pick one language. People in India mix Hindi and English in the same sentence, and Vaani keeps that mix.
- **Raw speech is messy.** "Um, so basically, kal 4 baje, nahi wait, 5 baje milte hain" becomes "Kal 5 baje milte hain."
- **Translation tools translate words, not meaning.** Google Translate turns Hindi idioms into nonsense English. Vaani uses your master adaptation prompts, which rebuild the *thought* in natural English or Hindi.
- **YouTube research takes hours.** A one-hour Hindi video becomes a readable English document in a few minutes, with timestamps.

### Who it helps most
- YouTube and Reels creators: scripts, research from other videos, subtitles.
- Anyone writing a lot of email, WhatsApp, or documents in English or Hinglish.
- Students and researchers turning lectures and interviews into notes.

---

## 3. One-time setup (about 15 minutes)

```
 STEP 1          STEP 2           STEP 3              STEP 4             STEP 5
 Install   ──►   Install    ──►   Get 2 API    ──►    Save keys   ──►    Download
 Python          ffmpeg           keys                on PC              Vaani
```

1. **Python**: download from https://www.python.org/downloads/. During install, tick **"Add python.exe to PATH"**.
2. **ffmpeg**: open PowerShell and run:
   ```
   winget install Gyan.FFmpeg
   ```
3. **API keys** (both are pay-as-you-go):
   - Claude: https://console.anthropic.com → API Keys → Create Key (starts with `sk-ant-`).
     Add a little credit under Billing.
   - Groq: https://console.groq.com → API Keys → Create (starts with `gsk_`).
4. **Save the keys.** In PowerShell (use your real keys):
   ```
   setx ANTHROPIC_API_KEY "sk-ant-..."
   setx GROQ_API_KEY "gsk_..."
   ```
   Then **close PowerShell and open a new window**. Keys only load in new windows.
5. **Download Vaani.** On https://github.com/peeyooshraj/vaani click **Code → Download ZIP**, then
   right-click the zip → **Extract All**.
   Put the folder somewhere simple, e.g. `C:\Vaani`. Avoid OneDrive or Desktop sync folders.

The first time you double-click either `.bat` file, it installs everything it needs into a `.venv` folder.
That takes 1–3 minutes, once.

---

## 4. Daily use

### A. Dictation
1. Double-click `start_dictation.bat`. A black window opens; **leave it open** (minimise it).
2. Click wherever you want text, such as a WhatsApp chat box.
3. **Hold Right Ctrl**, speak, **release**. You hear a beep up, a beep down, and the text appears in 1–3 seconds.
4. **Edit by voice:** select text, **hold Shift + Right Ctrl**, say e.g. "make this shorter and polite", release.
5. Quit: **Ctrl + Alt + Q**.

Tips:
- Self-corrections work: "Monday, no wait, Tuesday" gives "Tuesday".
- Spoken commands work: "new line", "new paragraph", "question mark".
- If you switch windows while it's working, nothing is pasted; the text goes on your clipboard. Press Ctrl+V.

### B. Transcribing a video or audio file
1. Double-click `transcribe.bat`.
2. Paste a YouTube link (or drag an audio/video file into the window) and press Enter.
3. Wait. A 10-minute video takes roughly 1–2 minutes.
4. Open `transcripts\<video title>\`:

| File | What's in it |
|---|---|
| `transcript_hinglish.md` (or `_hindi`, `_english`, `_other`) | Exactly what was said, cleaned up, in the spoken language |
| `english.md` | Natural English that adapts the meaning (made when the audio isn't English) |
| `raw_timestamped.txt` | Every line with its time, e.g. `[04:32]`, to jump back into the video |
| `subtitles_original.srt` | Subtitles you can load in YouTube Studio or a video editor |
| `hindi_<style>.md` | Only if you asked for Hindi/Hinglish (see below) |

**Extra options** (in a terminal opened inside the Vaani folder):
```
.venv\Scripts\python -m vaani.transcribe "LINK" --hindi hinglish-roman --context "Ramayana explainer, speaker is a historian"
```
- `--hindi devanagari | hinglish-devanagari | hinglish-roman`: also writes a Hindi/Hinglish script with your master prompt.
- `--context "..."`: tells it the topic and speakers, which improves names and terms.
- `--language hi`: forces the spoken language if auto-detection gets it wrong.
- `--fresh`: ignores saved progress and starts over.

If a run stops halfway (internet drop, closed window), run the same thing again. It continues from where it
stopped and doesn't pay twice for finished steps.

### C. Personalising (`dictionary.json`, `settings.json`)
Open them with Notepad.
- `dictionary.json` → `"words"`: names and terms it keeps getting wrong (your channel name, people, places).
- `dictionary.json` → `"snippets"`: say the trigger, get the full text
  (e.g. `"my sign off": "Thanks & regards,\nPeeyoosh"`).
- `settings.json` → `"dictation_output"`: `as_spoken` (default), `english` (always type English), or `hindi`.
- `settings.json` → `"hinglish_script"`: `roman` (Aaj meeting hai) or `devanagari`.
- `settings.json` → `"dictation_model"`: set `claude-haiku-5-5` for faster, cheaper typing.

---

## 5. How it works inside

```
 DICTATION
 key down ─► microphone (16 kHz) ─► key up ─► Whisper large-v3 (Groq)
          ─► Claude: remove fillers, apply corrections, punctuation, tone of the app, output language
          ─► window still the same? ─► yes: paste at cursor, restore your clipboard
                                     └► no: put text on clipboard, beep

 TRANSCRIPTION
 link/file ─► yt-dlp download ─► ffmpeg: mono 16 kHz, 10-min chunks ─► Whisper per chunk (timestamps)
          ─► save progress ─► Claude: faithful cleanup in the spoken language (detects English/Hindi/Hinglish/other)
          ─► save progress ─► Claude + english_adaptation.md: meaning-first English
          ─► save progress ─► (optional) Claude + hindi_adaptation.md: Hindi/Hinglish script
```

| Part | File | Job |
|---|---|---|
| Settings and checks | `vaani/config.py` | Reads settings, validates them, checks keys/ffmpeg before paid work |
| Speech-to-text | `vaani/stt.py` | Sends audio to Groq Whisper (or ElevenLabs) |
| AI text steps | `vaani/llm.py` | All Claude calls: cleanup, adaptation, dictation, commands |
| Audio handling | `vaani/media.py` | YouTube download, ffmpeg chunking, subtitles |
| Transcription flow | `vaani/transcribe.py` | Runs the pipeline with resume |
| Dictation app | `vaani/dictation.py` | Hotkeys, microphone, clipboard, pasting |
| Your prompts | `prompts/*.md` | The adaptation doctrine; edit these to change the writing style |

---

## 6. What it costs (rough, Nov 2026 prices)

| Task | Speech-to-text | Claude | Total, roughly |
|---|---|---|---|
| One dictation (10 seconds) | almost nothing | ~$0.002–0.01 | under ₹1 |
| 10-minute video → transcript + English | ~$0.02 | ~$0.05–0.15 | ₹5–15 |
| 1-hour video + English + Hindi | ~$0.10 | ~$0.40–1.00 | ₹40–90 |

Setting `dictation_model` to `claude-haiku-5-5` makes dictation far cheaper. Check real spend on the two consoles.

---

## 7. Where it fails: limitations to know

| Situation | What happens | Workaround |
|---|---|---|
| **Admin apps** (Task Manager, apps "Run as administrator") | Hotkeys and pasting don't reach them | Start Vaani as administrator too |
| **Image or file on the clipboard** | Replaced after dictation (only text is saved and restored) | Paste your image first, then dictate |
| **No internet** | Nothing works; everything runs in the cloud | None yet (see improvements) |
| **Noisy room, music, many speakers talking over each other** | Words dropped or garbled; `[unclear]` marks | Use a headset mic; clean audio |
| **Heavy dialect** (Bhojpuri, Haryanvi mixed with Hindi) | Whisper may mishear | Try `"stt_engine": "elevenlabs"`; add words to the dictionary |
| **Speaker labels** | Transcripts don't say who is speaking | Use `--context` to describe speakers; manual edit |
| **Private, age-restricted or members-only YouTube videos; live streams** | Download refused | Download the file yourself and drag it in |
| **YouTube changes its site** | Downloads break until yt-dlp updates | Run `.venv\Scripts\pip install -U yt-dlp` |
| **Very long first dictation** | Stops at 2 minutes (safety cap) | Speak in shorter bursts |
| **The AI adaptation itself** | Can occasionally soften a claim or pick a wrong idiom | Read `english.md` before publishing; the editorial notes flag changes |
| **Mac or Linux** | Dictation is Windows-only; transcription works anywhere | — |
| **Tested status** | Logic is tested (23 automated tests), but it hasn't yet run on a real Windows PC with real keys | Your first runs are the real test; report errors |

### Privacy
- Your voice and transcripts go to Groq (speech-to-text) and Anthropic (Claude). Nothing else leaves your PC.
- API keys live only in Windows environment variables, never in the code or on GitHub.
- Don't dictate passwords or card numbers.

---

## 8. Troubleshooting

| You see | Do this |
|---|---|
| `Python was not found` | Install Python (step 1), tick "Add to PATH", open a new window |
| `ANTHROPIC_API_KEY is not set` | Run the `setx` commands (step 4), then open a **new** window |
| `ffmpeg is not installed` | `winget install Gyan.FFmpeg`, new window |
| `microphone error` | Windows Settings → Privacy → Microphone → allow desktop apps; check the mic is plugged in |
| Nothing happens when holding Right Ctrl | Is the black window still open? Try running `start_dictation.bat` as administrator |
| `settings.json has a typo at line X` | Fix that line in Notepad (usually a missing quote or an extra comma) |
| Wrong language detected | Use `--language hi` or `--language en` |
| Anything else | Copy the whole error text and paste it to Claude |

---

## 9. How it could get better: improvement roadmap

| Idea | Benefit | Effort |
|---|---|---|
| **Tray icon** instead of a black window, with on/off and settings | Feels like a real app | Medium |
| **Live "listening" overlay** near the cursor | You see that it's recording | Medium |
| **Offline mode** with a local Whisper model | Works without internet, more private | Medium (needs a decent PC) |
| **Speaker labels** ("Speaker 1: …") | Better interview transcripts | Medium (ElevenLabs supports it) |
| **Use YouTube's own captions when present** | Faster and free for many videos | Small |
| **One-click installer (.exe)** | No Python setup for others | Medium |
| **Per-app styles** (WhatsApp casual, Gmail formal) as editable settings | More control over tone | Small |
| **History panel** of past dictations | Recover anything lost | Small |
| **Full clipboard save** (images and files too) | No clipboard loss | Small (needs pywin32) |
| **Inspect Wispr Flow with REA** once a PC is connected | Learn specific tricks it uses | Depends |
| **Batch mode**: a list of YouTube links | Research many videos at once | Small |
| **Direct export** to Google Docs or Notion | Fewer copy-paste steps | Medium |

---

## 10. Updating Vaani

When the code changes on GitHub:
1. Download the new ZIP from https://github.com/peeyooshraj/vaani.
2. Extract it over your old folder. **Keep your own `settings.json`, `dictionary.json` and `transcripts` folder.**
3. If `requirements.txt` changed, delete `.venv\installed.ok` so the next run reinstalls packages.
