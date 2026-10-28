"""Render LED-style PNG previews for the README (stdlib only): python3 tools/previews.py"""
import os, struct, sys, zlib
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from timebox import data, effects, gfx

OUT = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "docs", "img")
CELL, GAP = 14, 10


def png(path, w, h, rgb):
    raw = b"".join(b"\x00" + bytes(rgb[y * w * 3:(y + 1) * w * 3]) for y in range(h))
    chunk = lambda t, d: struct.pack(">I", len(d)) + t + d + struct.pack(">I", zlib.crc32(t + d))
    open(path, "wb").write(b"\x89PNG\r\n\x1a\n" + chunk(b"IHDR", struct.pack(">IIBBBBB", w, h, 8, 2, 0, 0, 0))
                           + chunk(b"IDAT", zlib.compress(raw, 9)) + chunk(b"IEND", b""))


def strip(name, frames, n=11):
    side = n * CELL
    w, h = len(frames) * side + (len(frames) - 1) * GAP, side
    buf = bytearray([11, 13, 12] * w * h)
    for i, f in enumerate(frames):
        ox = i * (side + GAP)
        for p, (r, g, b) in enumerate(f):
            cx, cy = ox + (p % n) * CELL + CELL // 2, (p // n) * CELL + CELL // 2
            col = (r, g, b) if (r, g, b) != (0, 0, 0) else (22, 30, 26)
            for y in range(cy - 6, cy + 6):
                for x in range(cx - 6, cx + 6):
                    if (x - cx + .5) ** 2 + (y - cy + .5) ** 2 <= 30:
                        o = (y * w + x) * 3
                        buf[o:o + 3] = bytes(col)
    png(os.path.join(OUT, name + ".png"), w, h, buf)


os.makedirs(OUT, exist_ok=True)
for n in ("fire", "fireworks", "matrix", "rainbow", "pacman", "sunrise"):
    fr = list(effects.EFFECTS[n](n=40))
    strip("anim-" + n, [fr[i] for i in (8, 16, 24, 32)])
strip("weather", data.weather_cards({"temp": 16, "code": 2}, "London") + [data.weather_frame({"temp": 24, "code": 0})] + [data.weather_frame({"temp": t, "code": c}) for t, c in ((9, 61), (-7, 73))])
strip("stocks", data.stock_cards("NVDA", 216.2, 2.5) + data.stock_cards("BTC-USD", 67234, -1.0))
cv = gfx.Canvas(); gfx.icon("mail", 0, 2, cv)
strip("notify", [cv.pixels()] + gfx.pages("HI THERE"))
print("wrote", sorted(os.listdir(OUT)))
bt = gfx.box_text("BACK AT 3PM", "yellow")[0]
strip("boxtext", [gfx.box_text("HI MOM", "pink")[0][0], bt[5], bt[9], bt[13]])

from timebox import proto
wf = data.weather_frame({"temp": 16, "code": 2})
for key, n in (("timeboxmini", 11), ("aurabox", 10), ("pixoo", 16), ("pixoomax", 32)):
    proto.set_model(key)
    strip("model-" + key, [proto.fit(wf)], n)
proto.set_model("timeboxmini")
