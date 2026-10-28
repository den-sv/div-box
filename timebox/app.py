"""Jobs, config, daemon and CLI. One process owns the Bluetooth port: the daemon if running, else the CLI itself."""
import argparse, datetime as dt, json, os, queue, socket, sys, threading, time
from . import data, effects, gfx, proto, sound as snd, sysinfo
from .device import Timebox
from .gfx import Canvas, color, text_or_scroll, icon, text_width

HOME = os.path.join(os.path.expanduser("~"), ".config", "timebox")
CONFIG, STATE = (os.path.join(HOME, n) for n in ("config.json", "state.json"))
DEFAULT_CONFIG = {
    "brightness": 70,
    "clock": {"h24": True, "color": "white"},
    "location": {"name": "London", "lat": 51.51, "lon": -0.13},
    "stocks": ["AAPL", "NVDA", "SPY"],
    "base": "clock",
    "rotation": {"every_min": 10, "show": ["weather", "stocks"]},
    "quiet": {"from": "23:00", "to": "07:00", "brightness": 8, "no_rotation": True},
    "alarms": [{"time": "07:30", "days": "mon-fri", "text": "GOOD MORNING", "anim": "sunrise", "sound": True, "on": False}],
    "reminders": [],
    "voice": {"name": "", "rate": 185, "out": "box", "keep_awake": True},
    "audio": {"volume": 8, "mute": False},
    "alerts": {"on": False, "step": 1.0, "every_min": 5, "sound": True, "speak": False},
    "chime": {"on": False, "speak": "It's {time}", "sound": "chime"},
}
DAYS = ["mon", "tue", "wed", "thu", "fri", "sat", "sun"]
FPS = 8


def load(path, default):
    try:
        with open(path) as f:
            return json.load(f)
    except (OSError, ValueError):
        return json.loads(json.dumps(default))


_save_lock = threading.Lock()
edit_lock = threading.RLock()      # hold around every cfg() -> change -> save(), so two saves can't undo each other


def save(path, obj):
    """Atomic write; own temp name per thread/process so simultaneous saves can't trip over each other."""
    os.makedirs(HOME, exist_ok=True)
    tmp = "%s.%d.%d.tmp" % (path, os.getpid(), threading.get_ident())
    with _save_lock:
        with open(tmp, "w") as f:
            json.dump(obj, f, indent=2)
        os.replace(tmp, path)


def cfg():
    c = load(CONFIG, DEFAULT_CONFIG)
    for k, v in DEFAULT_CONFIG.items():       # new settings appear in old config files
        c.setdefault(k, json.loads(json.dumps(v)))
    if not os.path.exists(CONFIG):
        save(CONFIG, c)
    return c


# --- jobs: lists of (pixels, seconds) or native-view callables ---------------------------
def job_text(text, col="white", times=1):
    return [(f, gfx.PAGE) for f in gfx.pages(text, color(col))] * times


def job_effect(name, secs=8):
    gen = effects.EFFECTS[name](n=int(secs * FPS))
    return [(f, 1 / FPS) for f in gen]


def job_notify(text, icon_name="mail", col="white", anim=None):
    frames = job_effect(anim, 3) if anim else []
    if icon_name:
        frames.append((icon(icon_name, 0, 2).pixels(), 1.5))
    return frames + job_text(text, col, 2)


def job_weather(c):
    loc = c["location"]
    w = data.weather(loc["lat"], loc["lon"])
    hi_lo = f"{w['hi']}/{w['lo']}"
    native = proto.weather(w["temp"], w["code"])           # Pixoo-generation boxes keep their own weather screen
    return ([(native, 0)] if native else []) + [(f, gfx.PAGE) for f in data.weather_cards(w, loc["name"])]


def job_stocks(symbols):
    out = []
    for s in symbols:
        try:
            p, pct = data.quote(s)
        except Exception:
            continue
        out += [(f, gfx.PAGE) for f in data.stock_cards(s.upper(), p, pct)]
    return out


def job_media(path, secs=10):
    if path.lower().endswith((".gif", ".mp4", ".mov", ".webp")):
        frames = gfx.load_video(path)
        loops = max(1, int(secs * 5 / max(1, len(frames))))
        return [(f, 0.2) for f in frames] * loops
    return [(gfx.load_image(path), secs)]


def timer_frame(end, total):
    left = max(0, end - time.time())
    cv = Canvas()
    m = int(left // 60) if left >= 60 else int(left)
    s = str(m)
    col = (255, 80, 0) if left >= 60 else (255, 0, 0)
    cv.text(s, (11 - text_width(s)) // 2, 1, col)
    filled = round(11 * 4 * left / total)           # 4 rows x 11 px progress bar
    for i in range(44):
        cv.set(i % 11, 7 + i // 11, (0, 160, 60) if i < filled else (25, 25, 25))
    if left >= 60:
        cv.set(10, 1, (120, 120, 120))              # little "m" marker dot
    return cv.pixels()


def job_date():
    now = dt.datetime.now()                     # one screen: OCT / 28
    return [(gfx.card(now.strftime("%b"), str(now.day), (255, 120, 0), WHITE_), gfx.PAGE)]


WHITE_ = (255, 255, 255)
ROTATION_ITEMS = "weather, stocks, date, sys, anim:NAME, text:MESSAGE, image:PATH"


def item_cmd(item):
    """Rotation entry ('weather', 'anim:fire', 'text:BLESS YOU', 'image:~/x.gif') -> command dict."""
    kind, _, arg = item.partition(":")
    if kind == "anim":
        return {"cmd": "anim", "name": arg or "rainbow", "secs": 8}
    if kind == "text":
        return {"cmd": "text", "text": arg, "color": "yellow"}
    if kind == "image":
        return {"cmd": "media", "path": os.path.expanduser(arg), "secs": 8}
    return {"cmd": kind}


def job_stock_alert(sym, price, pct):
    up = pct >= 0
    col = gfx.GREEN if up else gfx.RED
    cv = Canvas()
    rows = ["....#....", "...###...", "..#####..", ".#######.", "...###...", "...###...", "...###..."]
    cv.sprite(rows if up else rows[::-1], 1, 2, {"#": col})
    blank = Canvas().pixels()
    return [(cv.pixels(), 0.3), (blank, 0.15)] * 3 + [(f, gfx.PAGE) for f in data.stock_cards(sym, price, pct)]


def job_chime(c):
    now = dt.datetime.now()
    s = now.strftime("%H" if c["clock"]["h24"] else "%-I")
    cv = Canvas()
    cv.text(s, (11 - text_width(s)) // 2, 3, color(c["clock"]["color"]))
    return job_effect("spinner", 2) + [(cv.pixels(), 2)]


def build(cmd, c):
    """Turn a command dict (from CLI or schedule) into a job."""
    k = cmd["cmd"]
    gfx.PAGE = (c.get("rotation") or {}).get("page_secs", 2)      # seconds per still screen
    if k == "text":
        return job_text(cmd["text"], cmd.get("color", "white"), cmd.get("times", 1))
    if k == "anim":
        return job_effect(cmd["name"], cmd.get("secs", 8))
    if k == "notify":
        return job_notify(cmd["text"], cmd.get("icon", "mail"), cmd.get("color", "white"), cmd.get("anim"))
    if k == "weather":
        return job_weather(c)
    if k == "stocks":
        return job_stocks(cmd.get("symbols") or c["stocks"])
    if k == "media":
        return job_media(cmd["path"], cmd.get("secs", 10))
    if k == "date":
        return job_date()
    if k == "sys":
        return sysinfo.job()
    if k == "stock-alert":
        return job_stock_alert(cmd["sym"], cmd["price"], cmd["pct"])
    if k == "chime":
        return job_chime(c)
    if k == "alarm":
        job = job_effect(cmd["anim"], 6) if cmd.get("anim") else []
        if cmd.get("media"):                          # custom picture / GIF from the dashboard's media library
            path = os.path.join(HOME, "media", os.path.basename(cmd["media"]))
            if os.path.exists(path):
                job += job_media(path, 8)
        if cmd.get("text"):
            job += job_text(cmd["text"], cmd.get("color", "yellow"), 3)
        return job or job_effect("bell", 6)
    raise ValueError(f"unknown job {k}")


# --- the player ---------------------------------------------------------------------------
class Player:
    def __init__(self):
        self.tb = None
        self.c = cfg()
        self.preview = None        # last frame sent (121 px) or None while a built-in view shows
        self.view = "clock"        # what's on screen, for the dashboard
        self.lock = threading.RLock()

    def dev(self):
        while self.tb is None:
            try:
                self.tb = Timebox()
                set_link(True)
                self.tb.brightness(self.c["brightness"])
                au = self.c.get("audio") or {}
                self.tb.send(proto.volume(au.get("volume", 8) if au.get("beeps", True) else 0))
            except (OSError, SystemExit) as e:
                print("waiting for Timebox:", e, file=sys.stderr, flush=True)
                time.sleep(10)
        return self.tb

    def query(self, msg, cmd):
        with self.lock:
            try:
                return self.dev().query(msg, cmd)
            except OSError:
                self.tb = None

    def box_alarms(self):
        r = self.query(proto.get_alarms(), 0x42)
        return proto.parse_alarms(r or b"")

    def send(self, msg):
        if not msg:                      # command this model doesn't have
            return
        for _ in range(3):
            try:
                with self.lock:
                    return self.dev().send(msg)
            except OSError:
                try: self.tb.close()
                except Exception: pass
                self.tb = None
                set_link(False)

    def native(self, cmd):
        k, c = cmd["cmd"], self.c
        if k in ("clock", "temp", "off"):
            self.preview, self.view = None, k
        if k == "clock":
            cl = c["clock"]
            self.send(proto.set_time())
            self.send(proto.view(proto.VIEW_CLOCK, int(cmd.get("h24", cl["h24"])), color(cmd.get("color", cl["color"]))))
        elif k == "temp":
            self.send(proto.view(proto.VIEW_TEMP, int(cmd.get("f", c.get("temp_f", False))), color(cmd.get("color", c["clock"]["color"]))))
        elif k == "off":
            self.send(proto.view(proto.VIEW_OFF))
        elif k == "box-alarm":                         # stored on the box: rings without the Mac
            h, m = map(int, cmd["time"].split(":"))
            self.send(proto.set_time())
            self.send(proto.set_alarm(int(cmd["i"]), cmd.get("on", True), h, m, int(cmd.get("days", 0x7F)),
                                      cmd.get("ring", True), int(cmd.get("volume", 0)), bool(cmd.get("gif"))))
        elif k == "stop-ring":                         # A5 alone is unreliable, so also re-save the alarm that is ringing
            self.send(proto.frame(0xA5, b"\x00\x00\x00"))
            now = time.localtime(); mins = now.tm_hour * 60 + now.tm_min
            for a in self.box_alarms():
                h, m = map(int, a["time"].split(":"))
                if a["on"] and 0 <= (mins - h * 60 - m) % 1440 <= 5:      # rang in the last 5 minutes
                    args = (a["i"], True, h, m, a["days"], a["ring"], a["volume"], a["gif"])
                    self.send(proto.set_alarm(a["i"], False, *args[2:]))
                    self.send(proto.set_alarm(*args))
            self.native({"cmd": c.get("base", "clock")})
        elif k == "score":                             # box's own scoreboard (0x72), stays until you change screen
            self.preview, self.view = None, "score %d:%d" % (cmd.get("red", 0), cmd.get("blue", 0))
            self.send(proto.score(cmd.get("red", 0), cmd.get("blue", 0)))
        elif k in ("stopwatch", "visualizer"):           # documented built-in views (0x45 06 / 04)
            self.preview, self.view = None, k
            self.send(proto.view(proto.VIEW_STOPWATCH, 1) if k == "stopwatch" else proto.view(proto.VIEW_GRAPH, 0))
        elif k == "bright":
            self.send(proto.brightness(cmd["level"]))
        elif k == "volume":
            self.remember("audio", volume=cmd["level"])
            self.send(proto.volume(cmd["level"] if self.c["audio"].get("beeps", True) else 0))
        elif k == "beeps":       # the box's own sounds (hourly beep, button beeps) follow its volume; our audio doesn't
            self.remember("audio", beeps=bool(cmd.get("on", True)))
            self.send(proto.volume(self.c["audio"].get("volume", 8) if cmd.get("on", True) else 0))
        elif k == "mute":                              # software mute of our audio (0x0A is really play/pause on the box)
            self.remember("audio", mute=bool(cmd.get("on", True)))
        elif k == "upload":                         # loops on the device itself, no streaming
            frames = job_media(cmd["path"])
            self.preview, self.view = frames[0][0], "stored animation"
            self.remember("box", anim=os.path.basename(cmd["path"]), text=None)
            for msg in proto.animation([f for f, _ in frames[:cmd.get("max", 40)]], cmd.get("delay", 1)):
                self.send(msg)
        elif k == "boxtext":                        # message stored on the box as an animation
            col = cmd.get("color", "yellow")
            frames, shown, _ = gfx.box_text(cmd["text"], col, cmd.get("speed", "normal"),
                                            self.c.get("box", {}).get("max_frames", gfx.BOX_FRAMES))
            if not frames or not shown:
                return True
            self.preview, self.view = frames[0], "stored text"
            self.remember("box", anim="“%s”" % shown, text=dict(text=cmd["text"], color=col, speed=cmd.get("speed", "normal")))
            for msg in proto.animation(frames, 1):
                self.send(msg)
        else:
            return False
        return True

    def remember(self, section, **kv):
        with edit_lock:
            c = cfg()
            c.setdefault(section, {}).update(kv)
            save(CONFIG, c)
        self.c = c

    def play(self, job, stop=None):
        for px, secs in job:
            if stop and stop():
                return False
            if isinstance(px, bytes):                   # a ready protocol message inside a job
                self.send(px)
                continue
            self.preview, self.view = px, "stream"
            self.send(proto.image(px))
            time.sleep(secs)
        return True


def set_link(up):
    """Linux/Windows: record the link state for `tb status` / the dashboard (on macOS the bridge app does this)."""
    if sys.platform != "darwin":
        try:
            with open(os.path.join(HOME, "link"), "w") as f:
                f.write("up" if up else "down")
        except OSError:
            pass


def fx(cmd, c):
    """Play the job's sound and speak its text (through the box when it's a connected speaker)."""
    v = c.get("voice") or {}
    out = cmd.get("out") or v.get("out", "box")
    au = c.get("audio") or {}
    snd.GAIN = 0.0 if au.get("mute") else max(0, min(16, au.get("volume", 8))) / 16
    lead = v.get("lead_ms", 400)
    snd.WAKE_MS = lead
    if cmd.get("sound"):
        snd.play(cmd["sound"], out, lead)
    if cmd.get("speak"):
        if cmd.get("sound"):
            time.sleep(0.6)
        snd.say(snd.fill(cmd["speak"], c), cmd.get("voice") or v.get("name") or None, cmd.get("rate") or v.get("rate"), out, lead_ms=lead)


def in_window(now, frm, to):
    f, t, n = frm.replace(":", ""), to.replace(":", ""), now.strftime("%H%M")
    return f <= n < t if f <= t else n >= f or n < t


def day_ok(spec, now):
    if not spec or spec == "daily":
        return True
    today = DAYS[now.weekday()]
    for part in spec.lower().split(","):
        if "-" in part:
            a, b = (DAYS.index(p) for p in part.split("-"))
            if a <= DAYS.index(today) <= b:
                return True
        elif part.strip() == today or (part == "weekend" and today in ("sat", "sun")) or (part == "weekdays" and today not in ("sat", "sun")):
            return True
    return False


# --- daemon ---------------------------------------------------------------------------------
def daemon():
    p = Player()
    q = queue.Queue()
    os.makedirs(HOME, exist_ok=True)
    from . import web
    threading.Thread(target=web.serve, args=(p, q), daemon=True).start()
    threading.Thread(target=stock_watch, args=(p, q), daemon=True).start()
    threading.Thread(target=snd.keep_awake, args=(lambda: (p.c.get("voice") or {}).get("keep_awake", True),), daemon=True).start()

    mtime, fired, last_rot, last_min = 0, set(), time.time(), ""
    p.native({"cmd": p.c.get("base", "clock")})
    print("timebox daemon running", flush=True)
    while True:
        # reload config when edited
        m = os.path.getmtime(CONFIG) if os.path.exists(CONFIG) else 0
        if m != mtime:
            mtime, p.c = m, cfg()
        c, now = p.c, dt.datetime.now()
        st = load(STATE, {"timer": None})
        quiet = c.get("quiet") and in_window(now, c["quiet"]["from"], c["quiet"]["to"])

        # schedule (once per minute)
        hm = now.strftime("%H:%M")
        if hm != last_min:
            last_min = hm
            if hm == "03:00":
                p.send(proto.set_time())             # keep device clock honest
            p.send(proto.brightness(c["quiet"]["brightness"] if quiet else c["brightness"]))
            ch = c.get("chime") or {}
            if ch.get("on") and now.minute == 0 and not quiet:
                q.put({"cmd": "chime", "sound": ch.get("sound"), "speak": ch.get("speak")})
            for a in c.get("alarms", []):
                key = ("a", a["time"], a.get("text"), now.strftime("%F %H:%M"))
                if a.get("on", True) and a["time"] == hm and day_ok(a.get("days"), now) and key not in fired:
                    fired.add(key); q.put({"cmd": "alarm", **a})
            keep = []
            for r in c.get("reminders", []):
                if r["at"] <= now.strftime("%Y-%m-%d %H:%M"):
                    q.put({"cmd": "alarm", "text": r["text"], "anim": r.get("anim", "bell"), "sound": r.get("sound", True), "speak": r.get("speak")})
                else:
                    keep.append(r)
            if len(keep) != len(c.get("reminders", [])):
                c["reminders"] = keep; save(CONFIG, c); mtime = os.path.getmtime(CONFIG)

        # extras for alarms that ring on the box itself: a ringing box ignores pictures and drowns the voice
        # (and no command reliably stops the ring), so the Mac adds text/picture/voice 2 s after the box starts.
        # Verified: shows over a FLASH alarm; a RINGING box hides it (use flash + the Mac's voice for text alarms)
        soon = now + dt.timedelta(seconds=-2)          # a moment after the box starts its alarm
        for i_, e in (c.get("box_extras") or {}).items():
            key = ("x", i_, soon.strftime("%F %H:%M"))
            if e.get("on") and e.get("time") == soon.strftime("%H:%M") and now.second >= 2 \
                    and int(e.get("days", 0x7F)) >> soon.weekday() & 1 and key not in fired \
                    and (e.get("text") or e.get("media") or e.get("speak")):
                fired.add(key)
                q.put({"cmd": "alarm", "text": e.get("text"), "media": e.get("media"), "speak": e.get("speak"), "anim": e.get("anim"),
                       "color": e.get("color") or "yellow"})

        # timer finished?
        t = st.get("timer")
        if t and time.time() >= t["end"]:
            st["timer"] = None; save(STATE, st)
            q.put({"cmd": "alarm", "text": t.get("text", "TIME UP"), "anim": "fireworks", "sound": t.get("sound", True), "speak": t.get("speak")})

        # rotation
        rot = c.get("rotation") or {}
        if rot.get("every_min") and time.time() - last_rot > rot["every_min"] * 60 and not (quiet and c["quiet"].get("no_rotation")):
            last_rot = time.time()
            for what in rot.get("show", []):
                q.put({**item_cmd(what), "auto": True})

        try:
            cmd = q.get(timeout=1)
        except queue.Empty:
            if st.get("timer"):
                p.send(proto.image(timer_frame(st["timer"]["end"], st["timer"]["total"])))
            continue
        if cmd["cmd"] not in ("reload",):
            detail = cmd.get("text") or cmd.get("name") or cmd.get("level") or ""
            print(time.strftime("%H:%M:%S"), ("auto " if cmd.get("auto") else "") + cmd["cmd"], detail, flush=True)
        try:
            if cmd["cmd"] == "timer":
                st["timer"] = {"end": time.time() + cmd["secs"], "total": cmd["secs"], "text": cmd.get("text", "TIME UP"),
                               "speak": cmd.get("speak"), "sound": cmd.get("sound", True)}
                save(STATE, st); continue
            if cmd["cmd"] == "timer-stop":
                st["timer"] = None; save(STATE, st); p.native({"cmd": p.c.get("base", "clock")}); continue
            if cmd["cmd"] == "rotate-now":            # dashboard "try": play the saved rotation once
                for what in (p.c.get("rotation") or {}).get("show", []):
                    q.put(item_cmd(what))
                continue
            if cmd["cmd"] == "reload":
                mtime, last_min = 0, ""
                p.c = cfg(); p.native({"cmd": p.c.get("base", "clock")}); continue
            if p.native(cmd):
                continue
            if cmd["cmd"] in ("say", "sound"):
                fx({"sound": cmd.get("name"), "speak": cmd.get("text"), "voice": cmd.get("voice"),
                    "rate": cmd.get("rate"), "out": cmd.get("out")}, c)
                continue
            if quiet and cmd.get("auto"):
                cmd.pop("sound", None); cmd.pop("speak", None)
            fx(cmd, c)
            job = build(cmd, c)
            # anything interactive pre-empts automatic rotation items
            # only something YOU asked for (not the next rotation item) cuts a rotation item short
            p.play(job, stop=(lambda: any(not c.get("auto") for c in list(q.queue))) if cmd.get("auto") else None)
            if not st.get("timer") and q.empty():
                p.native({"cmd": p.c.get("base", "clock")})
        except Exception as e:
            print("job failed:", cmd, e, file=sys.stderr, flush=True)


def stock_watch(p, q):
    """Alert when a ticker's day change crosses another `step` % (e.g. +1%, +2%, -1% …)."""
    buckets = {}
    while True:
        a = p.c.get("alerts") or {}
        if a.get("on"):
            import math
            for sym in p.c.get("stocks", []):
                try:
                    price, pct = data.quote(sym)
                except Exception:
                    continue
                b = math.floor(pct / max(0.1, float(a.get("step", 1)))) if pct >= 0 else -math.floor(-pct / max(0.1, float(a.get("step", 1))))
                if sym in buckets and b != buckets[sym]:
                    up = b > buckets[sym]
                    q.put({"cmd": "stock-alert", "sym": sym, "price": price, "pct": pct, "auto": True,
                           "sound": ("tick-up" if up else "tick-down") if a.get("sound", True) else None,
                           "speak": f"{sym} {'up' if pct >= 0 else 'down'} {abs(pct):.1f} percent" if a.get("speak") else None})
                buckets[sym] = b
        time.sleep(max(1, float(a.get("every_min", 5))) * 60)


def send_to_daemon(cmd):
    """Hand a command to the running service through its local dashboard API. None when it isn't running."""
    import urllib.request
    from .web import PORT, token
    try:
        req = urllib.request.Request(f"http://127.0.0.1:{PORT}/api/cmd", data=json.dumps(cmd).encode(),
                                     headers={"X-Token": token(), "Content-Type": "application/json"})
        with urllib.request.urlopen(req, timeout=5) as r:
            return "ok" if json.load(r).get("ok") else "error"
    except (OSError, ValueError):
        return None


def run(cmd):
    """Send to the daemon if it's up, else drive the box directly."""
    if send_to_daemon(cmd) is not None:
        return
    if cmd["cmd"] in ("timer", "timer-stop", "reload"):
        raise SystemExit("timers need the daemon: tb daemon (or tb install-agent)")
    p = Player()
    if not p.native(cmd):
        if cmd["cmd"] in ("say", "sound"):
            return fx({"sound": cmd.get("name"), "speak": cmd.get("text"), "voice": cmd.get("voice"),
                       "rate": cmd.get("rate"), "out": cmd.get("out")}, p.c)
        fx(cmd, p.c)
        p.play(build(cmd, p.c))
        p.native({"cmd": p.c.get("base", "clock")})
    time.sleep(0.2)
    p.tb.close()
