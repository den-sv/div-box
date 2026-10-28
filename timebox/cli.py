"""tb — command line for the Divoom Timebox Mini."""
import argparse, datetime as dt, os, re, subprocess, sys
from . import effects, gfx, sound as snd
from .app import CONFIG, HOME, ROTATION_ITEMS, cfg, daemon, run, save, send_to_daemon

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
PID, LOG = os.path.join(HOME, "daemon.pid"), os.path.join(HOME, "daemon.log")


def parse_when(s):
    """'15:30', '+20m', '+2h', '2026-10-27 09:00' -> 'YYYY-MM-DD HH:MM'."""
    now = dt.datetime.now()
    s = s.strip().lower()
    if m := re.fullmatch(r"(?:in\s*)?\+?\s*(\d+)\s*([mh])[a-z]*", s):     # +20m, 20m, in 2h, 2 hours
        t = now + dt.timedelta(minutes=int(m[1]) * (60 if m[2] == "h" else 1))
    elif re.fullmatch(r"\d{1,2}:\d\d", s):
        t = dt.datetime.combine(now.date(), dt.time(*map(int, s.split(":"))))
        t += dt.timedelta(days=1) if t <= now else dt.timedelta()
    else:
        try:
            t = dt.datetime.strptime(s, "%Y-%m-%d %H:%M")
        except ValueError:
            raise SystemExit("when? try 15:30, +20m or 2h")
    return t.strftime("%Y-%m-%d %H:%M")


def parse_secs(s):
    m = re.fullmatch(r"(\d+)([smh]?)", s)
    if not m:
        raise SystemExit("duration like 25, 25m, 90s, 1h")
    return int(m[1]) * {"s": 1, "m": 60, "": 60, "h": 3600}[m[2]]


def daemon_pid():
    try:
        pid = int(open(PID).read())
        os.kill(pid, 0)
        return pid
    except (OSError, ValueError):
        return None


def start_daemon():
    if daemon_pid():
        send_to_daemon({"cmd": "reload"})
        print("already running - settings applied")
        return
    os.makedirs(HOME, exist_ok=True)
    p = subprocess.Popen([sys.executable, "-I", "-c",
                          "import sys; sys.path.insert(0, sys.argv[1]); from timebox.cli import main; main(['daemon'])", ROOT],
                         stdin=subprocess.DEVNULL, stdout=open(LOG, "a"), stderr=subprocess.STDOUT,
                         **({"creationflags": 0x00000008 | 0x00000200} if sys.platform == "win32"   # detached, own group
                            else {"start_new_session": True}))
    open(PID, "w").write(str(p.pid))
    print(f"started (pid {p.pid}) - stop with: tb stop")


def open_ui():
    import socket, time
    from .web import PORT, token
    if not daemon_pid():
        start_daemon()
    for _ in range(40):
        try:
            socket.create_connection(("127.0.0.1", PORT), 0.2).close()
            break
        except OSError:
            time.sleep(0.25)
    url = f"http://127.0.0.1:{PORT}/?k={token()}"
    import webbrowser
    webbrowser.open(url)
    print("dashboard:", url)


def stop_daemon():
    pid = daemon_pid()
    if pid:
        os.kill(pid, 15)
    if sys.platform == "darwin":
        subprocess.run(["pkill", "-f", "Timebox Bridge.app/Contents/MacOS/tbridge"], capture_output=True)
    for f in (PID, os.path.join(HOME, "link")):
        if os.path.exists(f):
            os.remove(f)
    print("stopped - everything off" if pid else "service was not running; Bluetooth link closed")


def status():
    c = cfg()
    link = open(os.path.join(HOME, "link")).read() if os.path.exists(os.path.join(HOME, "link")) else "bridge not running"
    rot = c.get("rotation", {})
    print(f"daemon     : {'running (pid %s)' % daemon_pid() if daemon_pid() else 'stopped'}")
    print(f"bluetooth  : {link}")
    from .models import MODELS, detect
    print(f"model      : {MODELS[detect()]['name']}  (change: tb model)")
    print(f"base       : {c.get('base', 'clock')}   brightness {c['brightness']}   clock {'24h' if c['clock']['h24'] else '12h'} {c['clock']['color']}")
    print(f"rotation   : every {rot.get('every_min') or 'off'} min -> {', '.join(rot.get('show', [])) or '-'}   ({rot.get('page_secs', 2)} s per screen)")
    print(f"stocks     : {', '.join(c['stocks'])}     city: {c['location']['name']}")
    q = c.get("quiet") or {}
    print(f"quiet      : {q.get('from', '-')}-{q.get('to', '-')} at brightness {q.get('brightness', '-')}")
    print(f"alarms     : {sum(a.get('on', True) for a in c['alarms'])} on / {len(c['alarms'])};  reminders pending: {len(c['reminders'])}")


def home():
    """Bare `tb`: make sure the service runs, then a short status, the dashboard link and the main commands."""
    import socket, time
    from .web import PORT, token
    if not daemon_pid():
        start_daemon()
        for _ in range(40):
            try:
                socket.create_connection(("127.0.0.1", PORT), 0.2).close()
                break
            except OSError:
                time.sleep(0.25)
    link = open(os.path.join(HOME, "link")).read().strip() if os.path.exists(os.path.join(HOME, "link")) else "connecting…"
    print(f"\n  ▚ timebox   service: running (pid {daemon_pid()})   box: {link}")
    print(f"  dashboard: http://127.0.0.1:{PORT}/?k={token()}\n")
    print("  tb ui                 open the dashboard")
    print("  tb text \"HI\"          show text        tb boxtext \"BACK AT 3\"  store text ON the box")
    print("  tb boxalarm list      box alarms       tb say \"hello\"          talk through the box")
    print("  tb score 3 1          scoreboard       tb clock                back to the clock")
    print("  tb status             details          tb -h                   every command")
    print("  tb exit               stop everything (service + Bluetooth link)\n")


def geocode(name):
    from .data import get
    import json, urllib.parse
    r = json.loads(get("https://geocoding-api.open-meteo.com/v1/search?count=1&name=" + urllib.parse.quote(name)))
    if not r.get("results"):
        raise SystemExit(f"city not found: {name}")
    g = r["results"][0]
    return {"name": g["name"], "lat": g["latitude"], "lon": g["longitude"]}


def add_settings_args(a):
    a.add_argument("--show", help="rotation items, comma separated: " + ROTATION_ITEMS + "  ('none' = off)")
    a.add_argument("--every", type=float, help="minutes between rotations (0 = off)")
    a.add_argument("--page", type=float, help="seconds each screen stays up (default 2)")
    a.add_argument("--base", choices=["clock", "temp", "off"], help="what stays on screen between rotations")
    a.add_argument("--stocks", help="tickers, comma separated, e.g. NVDA,AAPL,BTC-USD")
    a.add_argument("--city", help="weather city, e.g. Paris")
    a.add_argument("--bright", type=int, help="brightness 0-100")
    a.add_argument("--clock-color", help="white, red, cyan, #ff8800 ...")
    a.add_argument("--h12", action="store_true", help="12-hour clock"); a.add_argument("--h24", action="store_true", help="24-hour clock")
    a.add_argument("--quiet", help="night dimming window + level, e.g. 23:00-07:00@8, or 'off'")


def apply_settings(x):
    c, changed = cfg(), []
    if x.show is not None:
        c["rotation"]["show"] = [] if x.show == "none" else [i.strip() for i in x.show.split(",") if i.strip()]; changed.append("show")
    if x.every is not None:
        c["rotation"]["every_min"] = x.every; changed.append("every")
    if getattr(x, "page", None): c["rotation"]["page_secs"] = max(1, min(30, round(float(x.page)))); changed.append("page")
    if x.base: c["base"] = x.base; changed.append("base")
    if x.stocks: c["stocks"] = [t.strip().upper() for t in x.stocks.split(",")]; changed.append("stocks")
    if x.city: c["location"] = geocode(x.city); changed.append("city")
    if x.bright is not None: c["brightness"] = x.bright; changed.append("bright")
    if x.clock_color: c["clock"]["color"] = x.clock_color; changed.append("clock color")
    if x.h12 or x.h24: c["clock"]["h24"] = bool(x.h24); changed.append("12/24h")
    if x.quiet:
        if x.quiet == "off":
            c["quiet"] = None
        else:
            m = re.fullmatch(r"(\d\d:\d\d)-(\d\d:\d\d)(?:@(\d+))?", x.quiet) or sys.exit("quiet like 23:00-07:00@8")
            c["quiet"] = {"from": m[1], "to": m[2], "brightness": int(m[3] or 8), "no_rotation": True}
        changed.append("quiet")
    if changed:
        save(CONFIG, c)
    return changed


DAY_BITS = {"mon": 0, "tue": 1, "wed": 2, "thu": 3, "fri": 4, "sat": 5, "sun": 6}   # verified: bit0 = Monday


def days_mask(spec):
    spec = spec.lower()
    if spec in ("daily", "every"):
        return 0x7F
    if spec == "weekend":
        return 0x60
    if spec in ("weekdays", "mon-fri"):
        return 0x1F
    return sum(1 << DAY_BITS[d.strip()[:3]] for d in spec.split(","))


def days_text(mask):
    return {0x7F: "daily", 0x1F: "mon-fri", 0x60: "weekend", 0: "never"}.get(mask) or ",".join(d for d, b in DAY_BITS.items() if mask >> b & 1)


def boxalarm(x):
    from .app import Player
    if x.action in ("set", "off", "stop") or not send_to_daemon({"cmd": "reload"}):
        pass
    if x.action == "list":
        if send_to_daemon({"cmd": "reload"}):     # the service owns the link: ask the dashboard API
            import json, urllib.request
            from .web import PORT, token
            req = urllib.request.Request(f"http://127.0.0.1:{PORT}/api/boxalarms", headers={"X-Token": token(), "Host": "127.0.0.1"})
            alarms = json.load(urllib.request.urlopen(req, timeout=10))
        else:
            p = Player(); alarms = p.box_alarms(); p.tb.close()
        for a in alarms:
            print(f"[{a['i'] + 1}] {'ON ' if a['on'] else 'off'} {a['time']} {days_text(a['days']):9} {'MUSIC (re-save it!)' if a.get('music') and a['on'] else 'ring' if a['ring'] else 'silent'} {'alarm-anim' if a.get('gif') else 'clock'} vol {a['volume']}")
        return
    if x.action == "stop":
        return run({"cmd": "stop-ring"})
    if not x.slot or not 1 <= x.slot <= 3:
        raise SystemExit("slot 1-3")
    if x.action == "off":
        return run({"cmd": "box-alarm", "i": x.slot - 1, "on": False, "time": x.time or "00:00"})
    if not x.time:
        raise SystemExit("tb boxalarm set 1 07:30 [--days mon-fri] [--silent] [--volume 50]")
    run({"cmd": "box-alarm", "i": x.slot - 1, "on": True, "time": x.time, "days": days_mask(x.days),
         "ring": not x.silent, "volume": x.volume, "gif": x.gif})
    print(f"box alarm {x.slot}: {x.time} {x.days} {'silent' if x.silent or not x.volume else 'ring vol %d' % x.volume} (works without the Mac)")


def main(argv=None):
    ap = argparse.ArgumentParser(prog="tb", description="Divoom Timebox Mini from your Mac")
    sp = ap.add_subparsers(dest="cmd")
    a = sp.add_parser("clock", help="native clock"); a.add_argument("--12", dest="h12", action="store_true"); a.add_argument("--color", default=None)
    a = sp.add_parser("temp", help="box's own thermometer"); a.add_argument("--f", action="store_true"); a.add_argument("--color", default="white")
    sp.add_parser("off", help="display off")
    a = sp.add_parser("bright", help="brightness 0-100"); a.add_argument("level", type=int)
    a = sp.add_parser("volume", help="speaker volume 0-16"); a.add_argument("level", type=int)
    a = sp.add_parser("text", help="show/scroll text"); a.add_argument("text"); a.add_argument("--color", default="white"); a.add_argument("--times", type=int, default=1)
    a = sp.add_parser("anim", help="animation: " + ", ".join(effects.EFFECTS)); a.add_argument("name", choices=effects.EFFECTS); a.add_argument("--secs", type=float, default=8)
    a = sp.add_parser("image", help="show a picture or GIF (any size, auto-scaled to 11x11)"); a.add_argument("path"); a.add_argument("--secs", type=float, default=10)
    a = sp.add_parser("upload", help="put a GIF on the box itself (loops without the Mac, max 40 frames)"); a.add_argument("path"); a.add_argument("--delay", type=int, default=1)
    a = sp.add_parser("boxtext", help="store a message ON the box (loops with the computer off; long text is cut to whole words)")
    a.add_argument("text"); a.add_argument("--color", default="yellow"); a.add_argument("--speed", choices=list(gfx.SPEEDS), default="normal")
    a = sp.add_parser("score", help="scoreboard on the box: tb score 3 1 (red, blue)"); a.add_argument("red", type=int); a.add_argument("blue", type=int)
    sp.add_parser("weather", help="weather now (config: location)")
    a = sp.add_parser("stock", help="stock ticker(s)"); a.add_argument("symbols", nargs="*")
    a = sp.add_parser("notify", help="icon + text pop-up"); a.add_argument("text"); a.add_argument("--icon", default="mail", choices=list(gfx.ICONS) + ["none"])
    a.add_argument("--anim", choices=effects.EFFECTS); a.add_argument("--color", default="white"); a.add_argument("--sound", nargs="?", const="Glass", help="sound name (tb sounds)")
    a.add_argument("--speak", help="say this out loud too ({time} {temp} {weather} {city} {day} work)")
    a = sp.add_parser("timer", help="countdown on the box, e.g. tb timer 25m 'BREAK'"); a.add_argument("duration"); a.add_argument("text", nargs="?", default="TIME UP")
    a.add_argument("--speak", help="say this out loud too ({time} {temp} {weather} {city} {day} work)"); a.add_argument("--sound", default="Glass")
    sp.add_parser("timer-stop")
    a = sp.add_parser("remind", help="one-off reminder: tb remind 15:30 'CALL MOM' | +20m | '2026-10-27 09:00'")
    a.add_argument("when"); a.add_argument("text"); a.add_argument("--anim", default="bell", choices=effects.EFFECTS); a.add_argument("--quiet", action="store_true")
    a.add_argument("--speak", help="say this out loud too ({time} {temp} {weather} {city} {day} work)"); a.add_argument("--sound", default="Glass")
    a = sp.add_parser("alarm", help="repeating alarms")
    asp = a.add_subparsers(dest="action", required=True)
    b = asp.add_parser("add"); b.add_argument("time"); b.add_argument("--days", default="daily", help="daily | mon-fri | sat,sun | weekend")
    b.add_argument("--text", default="ALARM"); b.add_argument("--anim", default="sunrise", choices=effects.EFFECTS); b.add_argument("--quiet", action="store_true")
    b.add_argument("--speak", help="e.g. 'Good morning! It is {time}, {temp} and {weather} in {city}'"); b.add_argument("--sound", default="Glass")
    asp.add_parser("list")
    b = asp.add_parser("rm"); b.add_argument("index", type=int)
    b = asp.add_parser("on"); b.add_argument("index", type=int)
    b = asp.add_parser("off"); b.add_argument("index", type=int)
    a = sp.add_parser("say", help="speak through the box: tb say 'hello' [--voice Daniel] [--rate 200] [--mac]")
    a.add_argument("text"); a.add_argument("--voice"); a.add_argument("--rate", type=int); a.add_argument("--mac", action="store_true")
    a = sp.add_parser("sound", help="play a sound through the box (names: tb sounds)"); a.add_argument("name"); a.add_argument("--mac", action="store_true")
    a = sp.add_parser("beeps", help="the box's own beeps (hourly beep, buttons) on/off"); a.add_argument("state", choices=["on", "off"])
    a = sp.add_parser("boxalarm", help="alarms stored ON the box (ring without the Mac): list | set N HH:MM | off N | stop")
    a.add_argument("action", choices=["list", "set", "off", "stop"]); a.add_argument("slot", nargs="?", type=int); a.add_argument("time", nargs="?")
    a.add_argument("--days", default="daily", help="daily | mon-fri | weekend | sat,sun …"); a.add_argument("--silent", action="store_true", help="no sound, just the picture"); a.add_argument("--gif", action="store_true", help="show the box's built-in alarm animation instead of the flashing clock")
    a.add_argument("--volume", type=int, default=0, help="alarm loudness 0-16 like the box volume; default 0 = silent (1-2 = quiet)")
    a = sp.add_parser("address", help="save the box's Bluetooth address (Linux/Windows, if auto-detect fails)"); a.add_argument("addr")
    sp.add_parser("sounds", help="list sound names"); sp.add_parser("voices", help="list voices")
    sp.add_parser("sys", help="Mac stats on the box (cpu/ram/disk/battery bars + neofetch line)")
    a = sp.add_parser("alerts", help="stock move alerts: tb alerts on --step 1 --every 5 --speak")
    a.add_argument("state", choices=["on", "off"]); a.add_argument("--step", type=float); a.add_argument("--every", type=float)
    a.add_argument("--speak", action="store_true"); a.add_argument("--no-sound", action="store_true")
    a = sp.add_parser("chime", help="hourly chime: tb chime on --speak \"It's {time}\" --sound chime")
    a.add_argument("state", choices=["on", "off"]); a.add_argument("--speak"); a.add_argument("--sound")
    a = sp.add_parser("model", help="which Divoom box: show, or set one of " + ", ".join(__import__("timebox.models", fromlist=["x"]).MODELS) + ", or 'auto'")
    a.add_argument("name", nargs="?")
    sp.add_parser("config", help="print config path + contents")
    a = sp.add_parser("start", help="start the background service (alarms, reminders, timer, rotation) with optional settings"); add_settings_args(a)
    a = sp.add_parser("set", help="change settings (applied live if running)"); add_settings_args(a)
    sp.add_parser("ui", help="open the dashboard in your browser (starts the service if needed)")
    sp.add_parser("stop", help="stop the service and drop the Bluetooth link")
    sp.add_parser("exit", help="same as stop: everything off")
    sp.add_parser("status", help="what's running and what's configured")
    sp.add_parser("daemon", help="run the service in this terminal (foreground, Ctrl-C to quit)")
    x = ap.parse_args(argv)

    k = x.cmd
    if k is None:
        return home()
    if k == "daemon":
        return daemon()
    if k in ("start", "set"):
        changed = apply_settings(x)
        if k == "start":
            return start_daemon()
        if changed and not send_to_daemon({"cmd": "reload"}):
            print("saved (service not running - takes effect on tb start)")
        return status() if changed else print("nothing to change; see tb set -h")
    if k in ("stop", "exit"):
        return stop_daemon()
    if k == "ui":
        return open_ui()
    if k == "status":
        return status()
    if k == "config":
        print(CONFIG); print(open(CONFIG).read() if os.path.exists(CONFIG) else cfg()); return
    if k == "model":
        from . import models
        if x.name == "auto":
            if os.path.exists(models.MODEL_FILE): os.remove(models.MODEL_FILE)
        elif x.name:
            models.save(x.name)
        m = models.detect()
        print(f"model: {models.MODELS[m]['name']} ({m}) · {models.MODELS[m]['size']}x{models.MODELS[m]['size']}"
              + ("" if models.MODELS[m].get("tested") else " · untested, built from other projects' notes"))
        if x.name: print("restart the service to use it: tb exit && tb")
        return
    if k == "boxalarm":
        return boxalarm(x)
    if k == "address":
        from .device import ADDR_FILE
        os.makedirs(HOME, exist_ok=True)
        open(ADDR_FILE, "w").write(x.addr.strip().upper())
        return print("saved", x.addr.strip().upper())
    if k == "sounds":
        return print("  ".join(snd.sounds()))
    if k == "voices":
        return print("\n".join(f"{v['name']:28} {v['lang']}" for v in snd.voices()))
    if k in ("alerts", "chime"):
        c = cfg()
        sec = c[k]
        sec["on"] = x.state == "on"
        if k == "alerts":
            if x.step: sec["step"] = x.step
            if x.every: sec["every_min"] = x.every
            sec["speak"] = x.speak or sec.get("speak", False)
            if x.no_sound: sec["sound"] = False
        else:
            if x.speak: sec["speak"] = x.speak
            if x.sound: sec["sound"] = x.sound
        save(CONFIG, c); send_to_daemon({"cmd": "reload"})
        return print(k, sec)
    if k in ("remind", "alarm"):
        c = cfg()
        if k == "remind":
            at = parse_when(x.when)
            c["reminders"].append({"at": at, "text": x.text, "anim": x.anim, "sound": False if x.quiet else x.sound, "speak": x.speak})
            print("reminder set for", at)
        elif x.action == "add":
            c["alarms"].append({"time": x.time if len(x.time) == 5 else "0" + x.time, "days": x.days, "text": x.text,
                                "anim": x.anim, "sound": False if x.quiet else x.sound, "speak": x.speak, "on": True})
        elif x.action in ("rm", "on", "off"):
            if x.action == "rm":
                c["alarms"].pop(x.index)
            else:
                c["alarms"][x.index]["on"] = x.action == "on"
        for i, al in enumerate(c["alarms"]):
            print(f"[{i}] {'ON ' if al.get('on', True) else 'off'} {al['time']} {al.get('days', 'daily'):9} {al['text']} ({al.get('anim')})")
        save(CONFIG, c)
        if not send_to_daemon({"cmd": "reload"}):
            print("note: alarms/reminders fire only while the daemon runs (tb start)")
        return

    cmd = {"cmd": k}
    if k == "clock":
        cmd["h24"] = not x.h12
        if x.color: cmd["color"] = x.color
    elif k == "temp": cmd.update(f=x.f, color=x.color)
    elif k in ("bright", "volume"): cmd["level"] = x.level
    elif k == "text": cmd.update(text=x.text, color=x.color, times=x.times)
    elif k == "anim": cmd.update(name=x.name, secs=x.secs)
    elif k == "image": cmd = {"cmd": "media", "path": os.path.abspath(x.path), "secs": x.secs}
    elif k == "upload": cmd.update(path=os.path.abspath(x.path), delay=x.delay)
    elif k == "boxtext":
        cmd.update(text=x.text, color=x.color, speed=x.speed)
        shown = gfx.box_text(x.text, x.color, x.speed)[1]
        if shown != gfx._clean(x.text): print("too long for the box, stored:", shown)
    elif k == "score": cmd.update(red=x.red, blue=x.blue)
    elif k == "stock": cmd = {"cmd": "stocks", "symbols": [s.upper() for s in x.symbols]}
    elif k == "notify": cmd.update(text=x.text, icon=None if x.icon == "none" else x.icon, anim=x.anim, color=x.color, sound=x.sound, speak=x.speak)
    elif k == "timer": cmd.update(secs=parse_secs(x.duration), text=x.text, speak=x.speak, sound=x.sound)
    elif k == "say": cmd.update(text=x.text, voice=x.voice, rate=x.rate, out="mac" if x.mac else None)
    elif k == "sound": cmd.update(name=x.name, out="mac" if x.mac else None)
    elif k == "beeps": cmd["on"] = x.state == "on"
    run(cmd)


if __name__ == "__main__":
    main()
