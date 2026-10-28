"""Wire protocol (see docs/PROTOCOL.md, docs/MODELS.md): 01 | [escaped](len cmd args cs) | 02.
Content is drawn at SIZE x SIZE (11, the Mini) and fitted to the connected model's screen here."""
import datetime, math
from . import models

SIZE = 11
_model = None


def model():
    """The connected model's profile (detected once, see models.py)."""
    global _model
    if _model is None:
        _model = dict(models.MODELS[models.detect()], key=models.detect())
    return _model


def set_model(key):
    global _model
    _model = dict(models.MODELS[key], key=key)
VIEW_CLOCK, VIEW_TEMP, VIEW_OFF, VIEW_ANIM, VIEW_GRAPH, VIEW_IMAGE, VIEW_STOPWATCH, VIEW_SCORE = range(8)


def frame(cmd, args=b""):
    body = bytes([cmd]) + bytes(args)
    n = len(body) + 2
    payload = bytes([n & 0xFF, n >> 8]) + body
    cs = sum(payload) & 0xFFFF
    payload += bytes([cs & 0xFF, cs >> 8])
    if not model()["escape"]:
        return b"\x01" + payload + b"\x02"
    out = bytearray([0x01])
    for b in payload:
        out += bytes([0x03, b + 3]) if b in (1, 2, 3) else bytes([b])
    out.append(0x02)
    return bytes(out)


def unframe(raw):
    """Decode one 01..02 message to (cmd, args) or None."""
    data, esc = bytearray(), False
    for b in raw[1:-1]:
        if esc:
            data.append(b - 3); esc = False
        elif b == 3:
            esc = True
        else:
            data.append(b)
    if len(data) < 5 or (sum(data[:-2]) & 0xFFFF) != data[-2] | data[-1] << 8:
        return None
    return data[2], bytes(data[3:-2])


def pack_pixels(pixels):
    """pixels: 121 (r,g,b) 0-255 tuples, row-major -> 182 bytes, 4 bits/channel, low nibble first."""
    out = bytearray(182)
    n = 0
    for r, g, b in pixels:
        for v in (r, g, b):
            out[n >> 1] |= (v >> 4) << (4 if n & 1 else 0)
            n += 1
    return bytes(out)


def fit(pixels):
    """11x11 content -> the model's screen: centred on 16x16, doubled and centred on 32x32, cropped to 10x10."""
    n = model()["size"]
    if n == SIZE:
        return pixels
    k = 2 if n >= 2 * SIZE else 1
    off = (n - SIZE * k) // 2
    out = [(0, 0, 0)] * (n * n)
    for y in range(n):
        for x in range(n):
            sx, sy = (x - off) // k, (y - off) // k
            if 0 <= sx < SIZE and 0 <= sy < SIZE:
                out[y * n + x] = pixels[sy * SIZE + sx]
    return out


def _aura(pixels):
    """10x10, 3-bit colour (R=1 G=2 B=4 at >=128), two pixels per byte, first in the low nibble."""
    idx = [(r >= 128) | (g >= 128) << 1 | (b >= 128) << 2 for r, g, b in pixels]
    return bytes(idx[i] | idx[i + 1] << 4 for i in range(0, len(idx), 2))


def _palette_frame(pixels, ms=0):
    """Pixoo-generation frame: AA LEN(LE16) TIME(LE16) FLAG NCOL RGB... PIXELS (bit-packed indices, LSB first)."""
    big = model()["size"] > 16
    pal, idx = {}, []
    for p in pixels:
        idx.append(pal.setdefault(tuple(p), len(pal)))
    n = len(pal)
    bits = max(1, math.ceil(math.log2(n))) if n > 1 else 1
    acc = nb = 0
    packed = bytearray()
    for i in idx:
        acc |= i << nb
        nb += bits
        while nb >= 8:
            packed.append(acc & 0xFF); acc >>= 8; nb -= 8
    if nb:
        packed.append(acc & 0xFF)
    head = (b"\x03" + bytes([n & 0xFF, n >> 8])) if big else (b"\x00" + bytes([n & 0xFF]))   # 256 colours -> 0
    body = bytes([ms & 0xFF, ms >> 8 & 0xFF]) + head + b"".join(bytes(c) for c in pal) + bytes(packed)
    ln = len(body) + 3
    return b"\xAA" + bytes([ln & 0xFF, ln >> 8]) + body


def image(pixels):
    m = model()
    px = fit(pixels)
    if m["family"] == "mini":
        return frame(0x44, b"\x00\x0a\x0a\x04" + pack_pixels(px))
    if m["family"] == "aura":
        return frame(0x44, b"\x00\x0a\x0a\x04" + _aura(px))
    return frame(0x44, b"\x00\x0a\x0a\x04" + _palette_frame(px))


def anim_frame(pixels, index, delay=1):
    """Mini/Aurabox: one message per stored frame (delay unit ~200 ms on the Mini)."""
    px = fit(pixels)
    data = _aura(px) if model()["family"] == "aura" else pack_pixels(px)
    return frame(0x49, b"\x00\x0a\x0a\x04" + bytes([index & 0xFF, delay & 0xFF]) + data)


def animation(frames, delay=1):
    """All messages that store a looping animation on the box. delay in Mini units (~200 ms)."""
    if model()["family"] != "new":
        return [anim_frame(f, i, delay) for i, f in enumerate(frames)]
    big = model()["size"] > 16
    stream = b"".join(_palette_frame(fit(f), delay * 200) for f in frames[:60])
    if big:
        stream = b"\xAA\x08\x00\x00\x00\x05\x00\x00" + b"\xAA\x09\x00\x00\x00\x06\x00\x00\x00" + stream
    total, out = len(stream), []
    for n, k in enumerate(range(0, total, 200)):
        head = total.to_bytes(4, "little") + n.to_bytes(2, "little") if big else total.to_bytes(2, "little") + bytes([n])
        out.append(frame(0x49, head + stream[k:k + 200]))
    return out


def view(v, sub=0, color=None):
    """Built-in screens. Newer models number channels differently; unsupported ones give b'' (nothing sent)."""
    fam = model()["family"]
    if fam == "mini":
        args = bytes([v, sub])
        if color:
            args += bytes(color) + b"\xff"
        return frame(0x45, args)
    if fam == "aura":
        if v in (VIEW_CLOCK, VIEW_TEMP):
            return frame(0x45, bytes([v, sub]) + (bytes(color) if color and v == VIEW_CLOCK else b""))
        return frame(0x45, b"\x02") if v == VIEW_OFF else b""
    rgb = bytes(color or (255, 255, 255))
    if v == VIEW_CLOCK:          # 2D sets 12/24 h on Pixoo-generation boxes; 45 00 h24 style on weather temp cal RGB
        return frame(0x2D, bytes([sub])) + frame(0x45, bytes([0, sub, 0, 1, 0, 0, 0]) + rgb)
    if v == VIEW_TEMP:           # clock face with the temperature shown; unit via 2B
        return frame(0x2B, bytes([sub])) + frame(0x45, bytes([0, 1, 0, 1, 0, 1, 0]) + rgb)
    if v == VIEW_OFF:            # light channel with power 0
        return frame(0x45, b"\x01\x00\x00\x00\x00\x00\x00\x00\x00\x00")
    if v == VIEW_GRAPH:
        return frame(0x45, b"\x04\x00")
    return b""


def score(red, blue):
    """Scoreboard on the box: switch to the score screen, then set red : blue (0-999). Mini verified 2026-10-28:
    0x72 only changes what you see while the score screen is up. Newer boxes: score channel 6 (untested)."""
    r, b = (max(0, min(999, int(n))) for n in (red, blue))
    fam = model()["family"]
    if fam == "aura":
        return b""
    screen = view(VIEW_SCORE) if fam == "mini" else frame(0x45, b"\x06")
    return screen + frame(0x72, bytes([1, 1]) + r.to_bytes(2, "little") + b.to_bytes(2, "little"))


def weather(temp_c, code):
    """Pixoo-generation only: the box's own weather/temperature display. code: Open-Meteo weather code."""
    if model()["family"] != "new":
        return b""
    wx = 1 if code <= 1 else 3 if code <= 3 else 9 if code in (45, 48) else 8 if 71 <= code <= 77 or code in (85, 86) \
        else 5 if code >= 95 else 6
    return frame(0x5F, bytes([round(temp_c) & 0xFF, wx]))


def brightness(level):
    return frame(0x74, bytes([max(0, min(100, level))]))


def volume(level):
    m = model()
    if m.get("no_volume"):
        return b""
    level = max(0, min(16, level))
    return frame(0x08, bytes([level if m["family"] == "mini" else round(level * 15 / 16)]))


def set_time(t=None):
    t = t or datetime.datetime.now()
    wd = 0 if model()["family"] == "mini" else t.isoweekday() % 7          # newer boxes: weekday, 0 = Sunday
    return frame(0x18, bytes([t.year % 100, t.year // 100, t.month, t.day, t.hour, t.minute, t.second, wd]))


# --- box alarms (verified on a Timebox Mini: 3 slots, 10-byte records) -------------------
# record: index, on, hour, minute, weekday mask (bit0 = Mon … bit6 = Sun), mode (00 = flash only,
# 0A = flash + ring), trigger (01), fm hi/lo (00 00, never touch the radio), volume (0-100)
ALARM_SLOTS = 3


def get_alarms():
    return frame(0x42)


def set_alarm(i, on, hour, minute, days=0x7F, ring=True, volume=4, gif=False):
    """volume 0-16, same scale as the box's own volume (the record stores 0-100).
    gif=True: trigger 04 = the box's BUILT-IN alarm animation (not the uploaded one, checked 2026-10-27); 01 = flash clock.
    Silent = ring mode 0A with volume 0 (verified 2026-10-27). Never mode 00: that is "play Bluetooth music"
    (the box sends PLAY, which starts Music on the Mac) and it beeps when no music arrives."""
    vol = round(max(0, min(16, volume)) * 100 / 16) if ring else 0
    m = model()
    if m["family"] == "aura":
        return frame(0x43, bytes([hour, minute, 1, 0xFF if on else 0]))
    if m["family"] == "new":     # untested: weekday bit0 = Sunday; Pixoo/Max/Backpack take mode/trigger 0, volume 1
        days = ((days << 1) | (days >> 6)) & 0x7F
        if m.get("no_volume"):
            return frame(0x43, bytes([i, int(on), hour, minute, days, 0, 0, 0, 0, 1]))
    return frame(0x43, bytes([i, int(on), hour, minute, days & 0x7F, 0x0A, 4 if gif else 1, 0, 0, vol]))


def parse_alarms(payload):
    """0x42 reply payload (after the 55 ack byte) -> list of dicts."""
    out = []
    for k in range(0, len(payload) - 9, 10):
        r = payload[k:k + 10]
        days = r[4] if model()["family"] == "mini" else ((r[4] >> 1) | (r[4] << 6)) & 0x7F
        out.append({"i": r[0], "on": bool(r[1]), "time": f"{r[2]:02d}:{r[3]:02d}", "days": days,
                    "ring": r[5] != 0 and r[9] > 0, "music": r[5] == 0, "gif": r[6] == 4, "volume": round(r[9] * 16 / 100)})
    return out
