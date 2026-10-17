# flow_mini.py — hold F9 to dictate, release to paste
import os, re, time, threading, wave, collections, numpy as np, sounddevice as sd, keyboard, pyperclip, win32gui
from faster_whisper import WhisperModel
import anthropic
from opencc import OpenCC

env_path = os.path.join(os.path.dirname(os.path.abspath(__file__)), ".env")
if os.path.exists(env_path):  # KEY=value lines; real env vars win
    for line in open(env_path, encoding="utf-8-sig"):
        k, sep, v = line.strip().partition("=")
        if sep and not k.startswith("#"):
            os.environ.setdefault(k.strip(), v.strip().strip("\"'"))

SR = 16000
model = WhisperModel("base", device="cpu", compute_type="int8")  # multilingual, auto-detects language; faster than small
claude = anthropic.Anthropic() if os.getenv("ANTHROPIC_API_KEY") else None
if claude:  # warm the TLS connection so the first dictation doesn't pay for the handshake
    threading.Thread(target=lambda: claude.models.list(limit=1), daemon=True).start()
SKIP_WORDS = 8  # Whisper already punctuates; short phrases go straight to paste
LANGS = ("en", "zh")  # only pick between these; stops misdetection as ja/ko/etc.
t2s = OpenCC("t2s")  # Whisper often emits Traditional Chinese; convert deterministically
BLOCK = 512  # 32 ms per callback at 16 kHz
PREROLL_S = 0.5  # audio kept from before F9 goes down, so the first word isn't clipped
STALE_S = 0.5  # no callback for this long = stream is dead
pre = collections.deque(maxlen=int(PREROLL_S * SR / BLOCK) + 1)
frames, rec, stream, last_cb = [], False, None, 0.0
buf_lock, stream_lock = threading.Lock(), threading.Lock()

def cb(indata, n, t, status):
    global last_cb
    last_cb = time.time()
    with buf_lock:
        (frames if rec else pre).append(indata.copy())

def open_stream(reinit=False):
    global stream
    with stream_lock:
        if stream:
            try: stream.close()
            except Exception: pass
            stream = None
        if reinit:  # refresh PortAudio's device list (Bluetooth reconnect, default mic changed)
            sd._terminate(); sd._initialize()
        pre.clear()
        stream = sd.InputStream(samplerate=SR, channels=1, dtype="float32", blocksize=BLOCK, callback=cb)
        stream.start()

def healthy():
    if stream is None or not stream.active or time.time() - last_cb > STALE_S: return False
    with buf_lock:
        silent = len(pre) == pre.maxlen and all(not b.any() for b in pre)
    return not silent  # exact zeros = device delivering nothing

def watchdog():  # mic stays open; reopen it whenever it goes stale so pre-roll is always ready
    while True:
        time.sleep(2)
        if not rec and not healthy():
            print("[mic] stream stale, reopening", flush=True)
            try: open_stream(reinit=True)
            except Exception as ex: print(f"[mic] reopen failed: {ex}", flush=True)

def cleanup(raw, app):
    words = len(re.findall(r"[一-鿿]|[^\s一-鿿]+", raw))  # each CJK char counts as a word
    if not claude or not raw or words <= SKIP_WORDS: return raw
    try:
        r = claude.messages.create(model="claude-haiku-5-5", max_tokens=1024,
            thinking={"type": "disabled"},  # thinking blocks add latency and aren't text
            system=f"Clean up dictation for {app}: punctuation, drop fillers, apply self-corrections. "
                   "Keep the original language. Output only the text.",
            messages=[{"role": "user", "content": raw}])
        return "".join(b.text for b in r.content if b.type == "text").strip() or raw
    except Exception as ex:  # never lose the dictation over a cleanup failure
        print(f"[claude] failed, pasting raw: {type(ex).__name__}: {ex}", flush=True)
        return raw

def paste(text):
    old = pyperclip.paste()          # save, like mostRecentClipboardContentsString
    pyperclip.copy(text); time.sleep(0.03)
    keyboard.send("ctrl+v")          # SendInput under the hood
    time.sleep(0.25)                 # too short = old clipboard gets pasted (their xe() race)
    pyperclip.copy(old)

def finish(take):
    if not take: return
    audio = np.concatenate(take)[:, 0]
    with wave.open(os.path.join(os.path.dirname(os.path.abspath(__file__)), "last.wav"), "wb") as w:
        w.setnchannels(1); w.setsampwidth(2); w.setframerate(SR)  # keep last take for debugging
        w.writeframes((np.clip(audio, -1, 1) * 32767).astype(np.int16).tobytes())
    app = win32gui.GetWindowText(win32gui.GetForegroundWindow())
    t0 = time.time()
    segs, info = model.transcribe(audio, vad_filter=True, beam_size=1)  # greedy; detects language on VAD-trimmed audio
    lang, prob = info.language, info.language_probability
    if lang not in LANGS:  # rare: misdetected as ja/ko/etc., redo with the best of en/zh
        lang, prob = max(((l, p) for l, p in info.all_language_probs if l in LANGS), key=lambda x: x[1])
        segs, _ = model.transcribe(audio, language=lang, vad_filter=True, beam_size=1)
    raw = " ".join(s.text.strip() for s in segs)  # segs is lazy; decoding happens here
    if lang == "zh": raw = t2s.convert(raw)
    print(f"[audio {len(audio) / SR:.1f}s peak {np.abs(audio).max():.3f} | lang {lang} {prob:.2f}]", flush=True)
    t1 = time.time()
    text = cleanup(raw, app)
    t2 = time.time()
    print(f"[whisper {t1 - t0:.1f}s | claude {t2 - t1:.1f}s] {app!r}: {text!r}", flush=True)
    if text: paste(text)

def down(e):
    global rec
    if rec: return
    if not healthy():  # last-moment check; pre-roll is lost only when we have to reopen here
        print("[mic] stale on F9, reopening", flush=True)
        open_stream(reinit=True)
    with buf_lock:
        frames.clear(); frames.extend(pre); rec = True

def up(e):
    global rec
    if not rec: return
    with buf_lock:
        rec = False; take = frames[:]; frames.clear()
    threading.Thread(target=finish, args=(take,)).start()

open_stream()
threading.Thread(target=watchdog, daemon=True).start()

keyboard.on_press_key("f9", down, suppress=True)
keyboard.on_release_key("f9", up, suppress=True)
print(f"Ready. Hold F9 to dictate. Ctrl+C to quit. Claude cleanup: {'on' if claude else 'off'}", flush=True)
keyboard.wait()
