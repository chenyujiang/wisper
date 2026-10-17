# flow_mini — hold F9 to dictate

A lightweight voice dictation tool for Windows: hold F9 and speak, release it, and the transcription is pasted into whatever window has focus.

- Local speech recognition with `faster-whisper` (`base` model, CPU, int8)
- Language detection limited to Chinese / English, so speech is not misdetected as Japanese, Korean, etc.
- Chinese output is converted to Simplified Chinese (OpenCC `t2s`)
- Optional: with `ANTHROPIC_API_KEY` set, dictations longer than 8 words are cleaned up by Claude (`claude-haiku-5-5`): punctuation, filler removal, self-corrections applied. If the call fails, the raw transcription is pasted instead

## Requirements

- Windows (uses `pywin32` to read the foreground window title)
- Python 3.14 (the current `.venv` was created with 3.14.5)
- A working microphone

## Installation

```powershell
python -m venv .venv
.\.venv\Scripts\Activate.ps1
pip install -r requirements.txt
```

The Whisper `base` model is downloaded from Hugging Face on first run.

## Configuration

Optionally create a `.env` file in the project root. Without it, Claude cleanup is off.

```ini
ANTHROPIC_API_KEY=your-key
```

One `KEY=value` per line; lines starting with `#` are comments. Existing environment variables take precedence over `.env`.

## Usage

```powershell
.\.venv\Scripts\python.exe flow_mini.py
```

Once you see `Ready. Hold F9 to dictate.`:

1. Put the cursor where you want the text.
2. Hold F9 and speak.
3. Release F9. The text is pasted via clipboard + `Ctrl+V`, then the previous clipboard contents are restored.

Press `Ctrl+C` to quit.

Note: F9 is captured by this program, so other applications do not receive F9 while it runs. To dictate into a window running as administrator, run this program as administrator too.

## How it works

- The microphone stream stays open and keeps the 0.5 s of audio before F9 is pressed (pre-roll), so the first word is not clipped
- A background watchdog checks the stream every 2 s and reopens the device if callbacks stop or it delivers only silence (handles Bluetooth reconnects and default-mic changes)
- Transcription runs on a background thread after F9 is released, so it does not block the next dictation
- Each recording is saved as `last.wav` for debugging recognition issues

## Console output

```text
[audio 2.8s peak 0.412 | lang zh 0.97]
[whisper 0.6s | claude 0.9s] 'Window title': 'transcribed text'
```

- `peak` near 0: no sound from the microphone; check the input device
- `[mic] stream stale, reopening`: the microphone stream died and is being reopened
- `[claude] failed, pasting raw: ...`: Claude cleanup failed; the raw transcription was pasted

## Tunable parameters

At the top of `flow_mini.py`:

| Parameter | Default | Description |
| --- | --- | --- |
| `WhisperModel("base", ...)` | `base` | `small` / `medium` are more accurate but slower |
| `SKIP_WORDS` | `8` | Dictations with this many words or fewer skip Claude cleanup (each CJK character counts as one word) |
| `LANGS` | `("en", "zh")` | Allowed recognition languages |
| `PREROLL_S` | `0.5` | Seconds of audio kept from before F9 is pressed |
| `STALE_S` | `0.5` | Seconds without an audio callback before the microphone is considered dead |

## Files

- `flow_mini.py`: main program
- `requirements.txt`: pinned direct dependencies
- `.env`: API key configuration (do not commit it)
- `last.wav`: most recent recording
- `flow_mini.py.bak*`: backups of earlier versions
