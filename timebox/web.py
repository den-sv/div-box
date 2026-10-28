"""Dashboard: http://127.0.0.1:8411 — served by the daemon, localhost only, token-protected."""
import argparse, json, os, re, secrets, sys, time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from . import app, data, effects, gfx, sound as snd, sysinfo

PORT = 8411
TOKEN_FILE = os.path.join(app.HOME, "ui.token")
MEDIA = os.path.join(app.HOME, "media")
UI = os.path.join(os.path.dirname(__file__), "ui.html")
_cache = {}


def token():
    if not os.path.exists(TOKEN_FILE):
        os.makedirs(app.HOME, exist_ok=True)
        with open(os.open(TOKEN_FILE, os.O_WRONLY | os.O_CREAT, 0o600), "w") as f:
            f.write(secrets.token_urlsafe(16))
    return open(TOKEN_FILE).read().strip()


def hexpx(px):
    return "".join("%02x%02x%02x" % p for p in px) if px else None


def cached(key, ttl, fn):
    hit = _cache.get(key)
    if hit and time.time() - hit[0] < ttl:
        return hit[1]
    val = fn()
    _cache[key] = (time.time(), val)
    return val


def anims():
    return {n: [hexpx(f) for f in list(fn(n=24))] for n, fn in effects.EFFECTS.items()}


def quotes(symbols):
    out = []
    for s in symbols:
        try:
            p, pct = data.quote(s)
            out.append({"sym": s, "price": round(p, 2), "pct": round(pct, 2)})
        except Exception:
            out.append({"sym": s, "price": None, "pct": None})
    return out


def weather(c):
    w = data.weather(c["location"]["lat"], c["location"]["lon"])
    return {**w, "city": c["location"]["name"], "frame": hexpx(data.weather_frame(w))}


def media_list():
    os.makedirs(MEDIA, exist_ok=True)
    return sorted(f for f in os.listdir(MEDIA) if not f.startswith("."))


def media_frames(name):
    path = os.path.join(MEDIA, os.path.basename(name))
    frames = [f for f, _ in app.job_media(path, secs=0)][:30]
    return [hexpx(f) for f in frames]


def settings(d):
    """Dashboard settings dict -> same code path as `tb set`."""
    from .cli import apply_settings
    ns = argparse.Namespace(show=None, every=None, page=None, base=None, stocks=None, city=None, bright=None,
                            clock_color=None, h12=False, h24=False, quiet=None)
    for k, v in d.items():
        if k == "h24":
            ns.h24, ns.h12 = bool(v), not v
        elif hasattr(ns, k):
            setattr(ns, k, v)
    return apply_settings(ns)


def serve(player, q):
    tok = token()

    class H(BaseHTTPRequestHandler):
        def log_message(self, *a):
            pass

        def reply(self, obj, code=200, ctype="application/json"):
            body = obj if isinstance(obj, bytes) else json.dumps(obj).encode()
            self.send_response(code)
            self.send_header("Content-Type", ctype)
            self.send_header("Cache-Control", "no-store")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)

        def allowed(self):
            host = (self.headers.get("Host") or "").split(":")[0]
            if host not in ("127.0.0.1", "localhost"):          # blocks DNS-rebinding tricks
                return False
            if self.path.startswith("/api/"):
                return secrets.compare_digest(self.headers.get("X-Token", ""), tok)
            return True

        def do_GET(self):
            if not self.allowed():
                return self.reply({"error": "forbidden"}, 403)
            path, _, qs = self.path.partition("?")
            try:
                if path == "/":
                    if f"k={tok}" not in qs:
                        return self.reply(b"Open the dashboard with: tb ui", 403, "text/plain")
                    return self.reply(open(UI, "rb").read(), ctype="text/html; charset=utf-8")
                c = player.c
                if path == "/api/state":
                    st = app.load(app.STATE, {"timer": None})
                    t = st.get("timer")
                    link = os.path.join(app.HOME, "link")
                    log = os.path.join(app.HOME, "daemon.log")
                    return self.reply({
                        "link": open(link).read() if os.path.exists(link) else "down",
                        "view": player.view, "preview": hexpx(player.preview), "config": c,
                        "timer": {"left": max(0, t["end"] - time.time()), "total": t["total"], "text": t.get("text")} if t else None,
                        "log": open(log).read().splitlines()[-6:] if os.path.exists(log) else [],
                        "effects": list(effects.EFFECTS), "icons": list(gfx.ICONS), "colors": list(gfx.COLORS),
                        "media": media_list(), "now": time.strftime("%H:%M:%S"),
                        "sounds": snd.sounds(), "voices": [v["name"] for v in snd.voices()], "box_audio": snd.box_audio()})
                if path == "/api/sys":
                    log = os.path.join(app.HOME, "bridge.log")
                    mtu = re.findall(r"mtu (\d+)", open(log).read()) if os.path.exists(log) else []
                    from . import proto
                    return self.reply({"box": cached("sysbox", 20, sysinfo.box), "mtu": mtu[-1] if mtu else None, "model": proto.model()})
                if path == "/api/boxalarms":
                    return self.reply(player.box_alarms())
                if path == "/api/anims":
                    return self.reply(cached("anims", 3600, anims))
                if path == "/api/quotes":
                    return self.reply(cached("quotes" + ",".join(c["stocks"]), 60, lambda: quotes(c["stocks"])))
                if path == "/api/weather":
                    return self.reply(cached("weather" + c["location"]["name"], 600, lambda: weather(c)))
                if path == "/api/boxtext":                     # preview + fit info for text stored on the box
                    from urllib.parse import parse_qs
                    a = {k: v[0] for k, v in parse_qs(qs).items()}
                    mx = app.cfg().get("box", {}).get("max_frames", gfx.BOX_FRAMES)
                    frames, shown, trimmed = gfx.box_text(a.get("text", ""), a.get("color", "yellow"), a.get("speed", "normal"), mx)
                    return self.reply({"frames": [hexpx(f) for f in frames] if shown else [], "shown": shown,
                                       "trimmed": trimmed, "n": len(frames), "max": mx})
                if path == "/api/media":
                    name = re.sub(r"^name=", "", qs)
                    return self.reply(cached("m" + name, 3600, lambda: media_frames(name)))
                self.reply({"error": "not found"}, 404)
            except Exception as e:
                try:
                    self.reply({"error": str(e)}, 500)
                except BrokenPipeError:              # the browser tab went away mid-reply
                    pass

        def do_POST(self):
            if not self.allowed():
                return self.reply({"error": "forbidden"}, 403)
            n = int(self.headers.get("Content-Length") or 0)
            if n > 30_000_000:
                return self.reply({"error": "too big"}, 413)
            body = self.rfile.read(n)
            path = self.path.partition("?")[0]
            try:
                if path == "/api/upload":
                    name = re.sub(r"[^A-Za-z0-9._-]", "_", os.path.basename(self.headers.get("X-Name", "upload")))[-80:]
                    if not name.lower().endswith((".png", ".jpg", ".jpeg", ".gif", ".bmp", ".heic", ".webp", ".mp4", ".mov", ".tiff")):
                        return self.reply({"error": "pictures, GIFs or short videos only"}, 400)
                    os.makedirs(MEDIA, exist_ok=True)
                    open(os.path.join(MEDIA, name), "wb").write(body)
                    return self.reply({"ok": True, "name": name})
                d = json.loads(body or b"{}")
                with app.edit_lock:
                    return self.post(path, d)
            except SystemExit as e:
                self.reply({"error": str(e)}, 400)
            except Exception as e:
                self.reply({"error": str(e)}, 500)

        def post(self, path, d):
                if path == "/api/cmd" and d.get("cmd") == "open-sound":
                    import subprocess
                    if sys.platform == "darwin":
                        subprocess.run(["open", "x-apple.systempreferences:com.apple.Sound-Settings.extension"])
                    else:
                        return self.reply({"error": "pick the Timebox as output in your system's sound settings"}, 400)
                    return self.reply({"ok": True})
                if path == "/api/cmd":
                    if d.get("cmd") in ("media", "upload"):
                        d["path"] = os.path.join(MEDIA, os.path.basename(d.pop("name")))
                    q.put(d)
                    return self.reply({"ok": True})
                if path == "/api/settings":
                    changed = settings(d)
                    q.put({"cmd": "reload"})
                    _cache.clear()
                    return self.reply({"ok": True, "changed": changed})
                if path == "/api/schedule":
                    c = app.cfg()
                    act = d["action"]
                    if act == "alarm-add":
                        c["alarms"].append({"time": d["time"], "days": d.get("days") or "daily", "text": d.get("text") or "ALARM",
                                            "anim": d.get("anim") or None, "sound": d.get("sound", "Glass"),
                                            "speak": d.get("speak") or None, "media": d.get("media") or None,
                                            "color": d.get("color") or "yellow", "on": True})
                    elif act == "alarm-toggle":
                        c["alarms"][d["i"]]["on"] = not c["alarms"][d["i"]].get("on", True)
                    elif act == "alarm-rm":
                        c["alarms"].pop(d["i"])
                    elif act == "box-extra":                    # what the Mac shows when a box alarm rings
                        c.setdefault("box_extras", {})[str(d["i"])] = {k: d.get(k) for k in ("on", "time", "days", "text", "media", "speak", "anim", "color")}
                    elif act == "remind-add":
                        from .cli import parse_when
                        c["reminders"].append({"at": parse_when(d["when"]), "text": d.get("text") or "REMINDER",
                                               "anim": d.get("anim") or "bell", "sound": d.get("sound", "Glass"),
                                               "speak": d.get("speak") or None})
                    elif act == "remind-rm":
                        c["reminders"].pop(d["i"])
                    elif act == "media-rm":
                        os.remove(os.path.join(MEDIA, os.path.basename(d["name"])))
                    app.save(app.CONFIG, c)
                    q.put({"cmd": "reload"})
                    return self.reply({"ok": True})
                if path == "/api/section":                    # voice / alerts / chime / audio blocks
                    if d["section"] not in ("voice", "alerts", "chime", "audio", "display"):
                        return self.reply({"error": "unknown section"}, 400)
                    c = app.cfg()
                    if d["section"] == "display":                 # top-level display flags
                        c.update({k: v for k, v in d["values"].items() if k in ("temp_f",)})
                    else:
                        c.setdefault(d["section"], {}).update(d["values"])
                    app.save(app.CONFIG, c)
                    q.put({"cmd": "reload"})
                    return self.reply({"ok": True})
                if path == "/api/stop":
                    self.reply({"ok": True})
                    from .cli import stop_daemon
                    stop_daemon()
                    return
                self.reply({"error": "not found"}, 404)

    try:
        ThreadingHTTPServer(("127.0.0.1", PORT), H).serve_forever()
    except OSError as e:
        print("dashboard not started:", e, file=sys.stderr, flush=True)
