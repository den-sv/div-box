"""Voice + sound through the box's speaker (or the Mac's). Uses macOS `say` and ffmpeg's AudioToolbox output,
so the Mac's own sound output never changes. Falls back to the Mac speakers when the box isn't an audio device."""
import os, re, shutil, subprocess, sys, tempfile, threading, time

MAC, WIN = sys.platform == "darwin", sys.platform == "win32"

SYSTEM = "/System/Library/Sounds"
# synthesized blips: name -> ffmpeg lavfi source
SYNTH = {
    "tick-up": "sine=f=1760:d=0.06,volume=0.25",
    "tick-down": "sine=f=440:d=0.09,volume=0.25",
    "blip": "sine=f=1200:d=0.04,volume=0.2",
    "chime": "sine=f=880:d=0.18,volume=0.4[a];sine=f=1320:d=0.3,volume=0.4[b];[a][b]concat=n=2:v=0:a=1",
    "beep-beep": "sine=f=1000:d=0.12[a];anullsrc=d=0.1[s];sine=f=1000:d=0.12[b];[a][s][b]concat=n=3:v=0:a=1",
}
_cache = {}
# Bluetooth speakers sleep when idle: the first second of audio is lost while the stream wakes up.
# Everything sent to the box gets this much silence in front (config voice.lead_ms overrides).
LEAD_MS = 1500
# The box's own volume command doesn't touch the Bluetooth audio stream, so volume is applied to the audio itself.
GAIN = 0.5
WAKE_MS = 400       # hum before speech/sounds; dashboard "wake" slider (voice.lead_ms)


def _cached(key, ttl, fn):
    hit = _cache.get(key)
    if hit and time.time() - hit[0] < ttl:
        return hit[1]
    val = fn()
    _cache[key] = (time.time(), val)
    return val


def sounds():
    if not MAC:
        return list(SYNTH)
    sys_snd = sorted(f[:-5] for f in os.listdir(SYSTEM) if f.endswith(".aiff")) if os.path.isdir(SYSTEM) else []
    return list(SYNTH) + sys_snd


def voices():
    if not MAC:
        return []
    def load():
        out = subprocess.run(["say", "-v", "?"], capture_output=True, text=True).stdout
        return [{"name": m[1].strip(), "lang": m[2]} for m in re.finditer(r"^(.+?)\s+([a-z]{2}_[A-Z]{2}|[a-z]{2}_\d+)\s+#", out, re.M)]
    return _cached("voices", 3600, load)


def _say_device():
    if not MAC:
        return None
    def find():
        out = subprocess.run(["say", "-a", "?"], capture_output=True, text=True).stdout
        m = re.search(r"^\s*(\d+)\s+TimeBox", out, re.M | re.I)
        return m[1] if m else None
    return _cached("saydev", 20, find)


def _ff_device():
    if not MAC or not shutil.which("ffmpeg"):
        return None
    def find():
        out = subprocess.run(["ffmpeg", "-hide_banner", "-f", "lavfi", "-i", "anullsrc=d=0.01", "-f", "audiotoolbox",
                              "-list_devices", "true", "-"], capture_output=True, text=True).stderr
        m = re.search(r"\[(\d+)\]\s+TimeBox[^,]*,[^\n]*:output", out, re.I)   # the box is listed as mic (:input) too
        return m[1] if m else None
    return _cached("ffdev", 20, find)


def box_audio():
    """True when the box is currently usable as a speaker. Linux/Windows: whatever the default output is
    (make the Timebox your default speaker in the OS sound settings)."""
    return _say_device() is not None if MAC else bool(_tts_cmd(None, "x", "x.wav") and _player())


# --- Linux / Windows: speech to a WAV file, then play it on the default output -----------------------
def _tts_cmd(voice, text, wav):
    if WIN:
        ps = ("Add-Type -AssemblyName System.Speech; $s=New-Object System.Speech.Synthesis.SpeechSynthesizer; "
              + (f"$s.SelectVoice('{voice}'); " if voice else "") + f"$s.SetOutputToWaveFile('{wav}'); $s.Speak($env:TB_TEXT)")
        return ["powershell", "-NoProfile", "-Command", ps]
    for exe in ("espeak-ng", "espeak"):
        if shutil.which(exe):
            return [exe, *(["-v", voice] if voice else []), "-w", wav, text]
    return None


def _player():
    if WIN:
        return ["powershell", "-NoProfile", "-Command", "(New-Object Media.SoundPlayer $env:TB_WAV).PlaySync()"]
    for cmd in (["pw-play"], ["paplay"], ["aplay", "-q"], ["ffplay", "-nodisp", "-autoexit", "-loglevel", "error"]):
        if shutil.which(cmd[0]):
            return cmd
    return None


def _play_wav(path, block=False):
    cmd = _player()
    if not cmd:
        return
    env = {**os.environ, "TB_WAV": path}
    p = subprocess.Popen(cmd if WIN else cmd + [path], env=env, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    if block:
        p.wait()


def _wav(pcm, path):
    import wave
    with wave.open(path, "wb") as w:
        w.setnchannels(2); w.setsampwidth(2); w.setframerate(44100); w.writeframes(pcm)


def _portable(body_or_wav, is_file=False):
    """Hum + sound/speech as one WAV on the default output (Linux/Windows). Runs in a thread."""
    def run():
        with tempfile.TemporaryDirectory() as d:
            out = os.path.join(d, "out.wav")
            src = f"amovie='{body_or_wav.replace(os.sep, '/')}'" if is_file else body_or_wav
            pcm = wake_tone() + render(src) if shutil.which("ffmpeg") else None
            if pcm:
                _wav(pcm, out); _play_wav(out, block=True)
            elif is_file:
                _play_wav(body_or_wav, block=True)
    threading.Thread(target=run, daemon=True).start()


def say(text, voice=None, rate=None, out="box", wait=False, lead_ms=None):
    """Speak. For the box: render to a file first, then play it with real leading silence through ffmpeg.
    (`say -a` straight to a Bluetooth device clips the first words, and [[slnc]] doesn't help.)"""
    if not text:
        return
    if not MAC:
        def run():
            with tempfile.TemporaryDirectory() as d:
                wav = os.path.join(d, "say.wav")
                cmd = _tts_cmd(voice, text, wav)
                if not cmd:
                    return print("voice unavailable: install espeak-ng", file=sys.stderr)
                subprocess.run(cmd, env={**os.environ, "TB_TEXT": text}, capture_output=True)
                if os.path.exists(wav):
                    _portable(wav, is_file=True)
                    time.sleep(30)                         # keep the temp file until playback has read it
        threading.Thread(target=run, daemon=True).start()
        return
    opts = (["-v", voice] if voice else []) + (["-r", str(int(rate))] if rate else [])
    if out == "box" and _ff_device() is not None:
        import tempfile, threading
        def run():
            with tempfile.TemporaryDirectory() as d:
                f = os.path.join(d, "say.aiff")
                subprocess.run(["say", *opts, "-o", f, "--", text], capture_output=True)
                if SPEAKER and SPEAKER.alive():
                    SPEAKER.add(wake_tone() + render(f"amovie='{f}'"))
                else:
                    _ffplay(f"amovie='{f}'", _ff_device(), lead_ms, block=True)
        t = threading.Thread(target=run, daemon=True); t.start()
        if wait:
            t.join()
        return
    p = subprocess.Popen(["say", *opts, "--", f"[[volm {GAIN:.2f}]] {text}"], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    if wait:
        p.wait()


def _ffplay(body, dev, lead_ms=None, block=False):
    lead = LEAD_MS if lead_ms is None else int(lead_ms)
    fmt = f"volume={GAIN:.2f},aresample=44100,aformat=channel_layouts=stereo[main]"
    body = f"{body}[raw];[raw]{fmt}" if ";" in body else f"{body},{fmt}"   # multi-part synths end unlabeled
    graph = f"anullsrc=r=44100:cl=stereo:d={lead / 1000}[lead];{body};[lead][main]concat=n=2:v=0:a=1"
    p = subprocess.Popen(["ffmpeg", "-v", "error", "-filter_complex", graph, "-f", "audiotoolbox", "-audio_device_index", dev, "-"],
                         stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    if block:
        p.wait()


def play(name="Glass", out="box", lead_ms=None):
    if not name:
        return
    if name is True:
        name = "Glass"
    if not MAC:
        if name in SYNTH:
            _portable(SYNTH[name])
        return
    dev = _ff_device() if out == "box" else None
    path = os.path.join(SYSTEM, name + ".aiff")
    if dev is not None:
        body = SYNTH[name] if name in SYNTH else f"amovie='{path}'"
        if SPEAKER and SPEAKER.alive():
            import threading
            threading.Thread(target=lambda: SPEAKER.add(wake_tone() + render(body)), daemon=True).start()
        else:
            _ffplay(body, dev, lead_ms)
    elif os.path.exists(path):
        subprocess.Popen(["afplay", path])
    elif name in SYNTH and shutil.which("ffmpeg"):
        src = ["-filter_complex", SYNTH[name]] if ";" in SYNTH[name] else ["-f", "lavfi", "-i", SYNTH[name]]
        subprocess.Popen(["ffmpeg", "-v", "error", *src, "-f", "audiotoolbox", "-"],
                         stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)


def fill(text, c):
    """{time} {date} {day} {city} {temp} {weather} {hi} {lo} placeholders for spoken messages."""
    if not text or "{" not in text:
        return text
    import datetime as dt
    now = dt.datetime.now()
    vals = {"time": now.strftime("%-I:%M %p" if not c["clock"]["h24"] else "%H:%M"),
            "date": now.strftime("%B %-d"), "day": now.strftime("%A"), "city": c["location"]["name"]}
    if any(k in text for k in ("{temp}", "{weather}", "{hi}", "{lo}")):
        try:
            from . import data
            w = data.weather(c["location"]["lat"], c["location"]["lon"])
            words = {"sun": "sunny", "partly": "partly cloudy", "cloud": "cloudy", "fog": "foggy",
                     "snow": "snowy", "storm": "stormy", "rain": "rainy"}
            vals.update(temp=f"{w['temp']} degrees", hi=str(w["hi"]), lo=str(w["lo"]), weather=words[data.weather_icon(w["code"])])
        except Exception:
            pass
    for k, v in vals.items():
        text = text.replace("{" + k + "}", v)
    return text


class Speaker:
    """One never-ending PCM stream into the box. Starting a new audio stream on a Bluetooth speaker clips its first
    second, so instead we keep a single stream open (silence when idle) and splice speech/sounds into it."""
    RATE, CH = 44100, 2
    CHUNK = RATE * CH * 2 // 20            # 50 ms of s16 stereo

    def __init__(self, dev):
        import collections, threading
        self.dev, self.buf, self.lock = dev, collections.deque(), threading.Lock()
        self.proc = subprocess.Popen(["ffmpeg", "-v", "error", "-f", "s16le", "-ar", str(self.RATE), "-ac", str(self.CH),
                                      "-i", "pipe:0", "-f", "audiotoolbox", "-audio_device_index", dev, "-"],
                                     stdin=subprocess.PIPE, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        threading.Thread(target=self._feed, daemon=True).start()

    def alive(self):
        return self.proc.poll() is None

    def stop(self):
        try:
            self.proc.stdin.close()
        except Exception:
            pass
        self.proc.terminate()

    def add(self, pcm):
        with self.lock:
            for i in range(0, len(pcm), self.CHUNK):
                self.buf.append(pcm[i:i + self.CHUNK].ljust(self.CHUNK, b"\0"))

    def _feed(self):
        # not digital zeros: speakers like this one gate their amplifier on pure silence and take ~1 s to open it
        # again. A -66 dBFS hiss keeps the amp open and is inaudible.
        import random, struct
        rnd = random.Random(7)
        silence = struct.pack(f"<{self.CHUNK // 2}h", *(rnd.randint(-16, 16) for _ in range(self.CHUNK // 2)))
        t, ahead = time.time(), 0.2       # stay ~200 ms ahead of the device
        while self.alive():
            with self.lock:
                chunk = self.buf.popleft() if self.buf else silence
            try:
                self.proc.stdin.write(chunk); self.proc.stdin.flush()
            except Exception:
                return
            t += 0.05
            time.sleep(max(0, t - time.time() - ahead))


SPEAKER = None


def wake_tone(ms=None):
    """A deep 30 Hz hum the tiny speaker can't really reproduce, but loud enough to open the box's
    auto-mute gate before the first word arrives."""
    ms = WAKE_MS if ms is None else ms
    if ms <= 0:
        return b""
    return render(f"sine=f=30:d={ms / 1000},volume=0.6,afade=t=in:d=0.1,afade=t=out:st={ms / 1000 - 0.1}:d=0.1", gain=False)


def render(body, gain=True):
    """ffmpeg filter source -> raw PCM at the speaker's format, with the current volume applied."""
    fmt = (f"volume={GAIN:.2f}," if gain else "") + "aresample=44100,aformat=sample_fmts=s16:channel_layouts=stereo"
    graph = f"{body}[raw];[raw]{fmt}" if ";" in body else f"{body},{fmt}"
    return subprocess.run(["ffmpeg", "-v", "error", "-filter_complex", graph, "-f", "s16le", "-"],
                          capture_output=True).stdout


def keep_awake(get_enabled):
    """Keep the persistent Speaker running while enabled and the box is an audio device (re-created after drops)."""
    global SPEAKER
    while True:
        dev = _ff_device() if get_enabled() else None
        if SPEAKER and (not SPEAKER.alive() or SPEAKER.dev != dev):
            SPEAKER.stop(); SPEAKER = None
        if dev is not None and SPEAKER is None:
            SPEAKER = Speaker(dev)
        time.sleep(5)
