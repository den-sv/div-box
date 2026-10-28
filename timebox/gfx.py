"""11x11 canvas, 3x5 pixel font, icons, image/GIF loading (macOS sips; ffmpeg for GIF/video if present)."""
import os, shutil, struct, subprocess, tempfile
from .proto import SIZE

BLACK, WHITE = (0, 0, 0), (255, 255, 255)
RED, GREEN, BLUE = (255, 0, 0), (0, 255, 0), (0, 80, 255)
YELLOW, ORANGE, CYAN, PINK, GREY = (255, 200, 0), (255, 100, 0), (0, 200, 255), (255, 0, 160), (90, 90, 90)
COLORS = dict(black=BLACK, white=WHITE, red=RED, green=GREEN, blue=BLUE, yellow=YELLOW,
              orange=ORANGE, cyan=CYAN, pink=PINK, grey=GREY, purple=(150, 0, 255))


def color(c):
    if isinstance(c, tuple):
        return c
    if c.startswith("#"):
        return tuple(int(c[i:i + 2], 16) for i in (1, 3, 5))
    return COLORS[c]


class Canvas:
    def __init__(self, w=SIZE, h=SIZE, bg=BLACK):
        self.w, self.h = w, h
        self.px = [[bg] * w for _ in range(h)]

    def set(self, x, y, c):
        if 0 <= x < self.w and 0 <= y < self.h:
            self.px[y][x] = c

    def get(self, x, y):
        return self.px[y][x] if 0 <= x < self.w and 0 <= y < self.h else BLACK

    def rect(self, x, y, w, h, c):
        for yy in range(y, y + h):
            for xx in range(x, x + w):
                self.set(xx, yy, c)

    def sprite(self, rows, x=0, y=0, palette=None):
        """rows: strings; '.' is transparent, other chars map through palette (default: any char = white)."""
        for dy, row in enumerate(rows):
            for dx, ch in enumerate(row):
                if ch != ".":
                    self.set(x + dx, y + dy, (palette or {}).get(ch, WHITE))

    def text(self, s, x=0, y=0, c=WHITE):
        for ch in s.upper():
            glyph = FONT.get(ch, FONT["?"])
            for dy, bits in enumerate(glyph):
                for dx in range(len(bits)):
                    if bits[dx] == "#":
                        self.set(x + dx, y + dy, c)
            x += len(glyph[0]) + 1
        return x

    def window(self, x0=0, y0=0):
        """121 pixels of an 11x11 view starting at (x0, y0)."""
        return [self.get(x0 + x, y0 + y) for y in range(SIZE) for x in range(SIZE)]

    def pixels(self):
        return self.window()


def text_width(s):
    return sum(len(FONT.get(ch, FONT["?"])[0]) + 1 for ch in s.upper()) - 1


def scroll_frames(s, c=WHITE, y=3, bg=BLACK):
    """Frames that scroll s right-to-left through the display."""
    w = text_width(s)
    cv = Canvas(w + 2 * SIZE, SIZE, bg)
    cv.text(s, SIZE, y, c)
    return [cv.window(x) for x in range(w + SIZE + 1)]


PAGE = 2          # seconds per screen: everything is shown as still screens, never scrolled


def card(top, bottom=None, ctop=WHITE, cbot=None):
    """One 11x11 screen: two centred lines (or one line in the middle). About 3 characters per line."""
    cv = Canvas()
    if bottom is None:
        cv.text(top, (SIZE - text_width(top)) // 2, 3, ctop)
    else:
        cv.text(top, (SIZE - text_width(top)) // 2, 0, ctop)
        cv.text(bottom, (SIZE - text_width(bottom)) // 2, 6, cbot or ctop)
    return cv.pixels()


def fit_word(w):
    while text_width(w) > SIZE:
        w = w[:-1]
    return w


def pages(s, c=WHITE):
    """Text as still screens of up to two short lines each (words that are too long get cut)."""
    lines = []
    for word in s.split():
        word = fit_word(word)
        if lines and text_width(lines[-1] + " " + word) <= SIZE:
            lines[-1] += " " + word
        elif word:
            lines.append(word)
    if not lines:
        return [card("")]
    if len(lines) == 1:
        return [card(lines[0], None, c)]
    return [card(lines[i], lines[i + 1] if i + 1 < len(lines) else "", c) for i in range(0, len(lines), 2)]


def text_or_scroll(s, c=WHITE, y=3):
    """Kept for old callers: now always still screens (see pages)."""
    return pages(s, c)


# --- 3x5 font (1-px glyphs for narrow punctuation) -----------------------------------------
_F = """
0 ### #.# #.# #.# ###|1 .#. ##. .#. .#. ###|2 ### ..# ### #.. ###|3 ### ..# .## ..# ###
4 #.# #.# ### ..# ..#|5 ### #.. ### ..# ###|6 ### #.. ### #.# ###|7 ### ..# .#. .#. .#.
8 ### #.# ### #.# ###|9 ### #.# ### ..# ###|A .#. #.# ### #.# #.#|B ##. #.# ##. #.# ##.
C .## #.. #.. #.. .##|D ##. #.# #.# #.# ##.|E ### #.. ##. #.. ###|F ### #.. ##. #.. #..
G .## #.. #.# #.# .##|H #.# #.# ### #.# #.#|I ### .#. .#. .#. ###|J ..# ..# ..# #.# .#.
K #.# #.# ##. #.# #.#|L #.. #.. #.. #.. ###|M #.# ### ### #.# #.#|N ##. #.# #.# #.# #.#
O .#. #.# #.# #.# .#.|P ##. #.# ##. #.. #..|Q .#. #.# #.# ##. .##|R ##. #.# ##. #.# #.#
S .## #.. .#. ..# ##.|T ### .#. .#. .#. .#.|U #.# #.# #.# #.# ###|V #.# #.# #.# #.# .#.
W #.# #.# ### ### #.#|X #.# #.# .#. #.# #.#|Y #.# #.# .#. .#. .#.|Z ### ..# .#. #.. ###
- ... ... ### ... ...|+ ... .#. ### .#. ...|% #.. ..# .#. #.. ..#|/ ..# ..# .#. #.. #..
? ### ..# .## ... .#.|$ .## ##. .#. .## ##.|= ... ### ... ### ...|' # # . . .
. . . . . #|: . # . # .|! # # # . #|, . . . # #|° ### #.# ### ... ...
  ... ... ... ... ...|( .# #. #. #. .#|) #. .# .# .# #.|> #.. .#. ..# .#. #..|< ..# .#. #.. .#. ..#
"""
FONT = {}
for line in _F.strip("\n").split("\n"):
    for item in line.split("|"):
        ch, rows = item[0], item[2:].split(" ")
        FONT[ch] = rows
FONT[" "] = ["..", "..", "..", "..", ".."]


# --- icons ------------------------------------------------------------------------------
ICONS = {
    "sun": (["...Y.Y.Y...", "....YYY....", "..YYYYYYY..", "....YYY....", "...Y.Y.Y...", "..........."],
            {"Y": YELLOW}),
    "cloud": (["...........", "...WWW.....", "..WWWWWWW..", ".WWWWWWWWW.", ".WWWWWWWWW.", "..........."], {"W": (200, 200, 200)}),
    "partly": (["......Y.Y..", ".......YY..", "...WWWYYYY.", "..WWWWWWY..", ".WWWWWWWW..", ".WWWWWWWWW."],
               {"Y": YELLOW, "W": (200, 200, 200)}),
    "rain": (["...WWW.....", "..WWWWWWW..", ".WWWWWWWWW.", "...........", "..B..B..B..", ".B..B..B..."],
             {"W": (150, 150, 170), "B": CYAN}),
    "snow": (["...WWW.....", "..WWWWWWW..", ".WWWWWWWWW.", "...........", "..S...S..S.", "....S...S.."],
             {"W": (150, 150, 170), "S": WHITE}),
    "storm": (["...WWW.....", "..WWWWWWW..", ".WWWWWWWWW.", ".....YY....", "....YY.....", "...Y......."],
              {"W": (110, 110, 130), "Y": YELLOW}),
    "fog": (["...........", ".WWWWWWWWW.", "...........", "..WWWWWWW..", "...........", ".WWWWWWWWW."], {"W": GREY}),
    "up": (["....G....", "...GGG...", "..GGGGG..", "....G....", "....G...."], {"G": GREEN}),
    "down": (["....R....", "....R....", "..RRRRR..", "...RRR...", "....R...."], {"R": RED}),
    "bell": (["....Y......", "...YYY.....", "..YYYYY....", "..YYYYY....", ".YYYYYYY...", "....O......"],
             {"Y": YELLOW, "O": ORANGE}),
    "mail": (["WWWWWWWWWWW", "WW.......WW", "W.W.....W.W", "W..W...W..W", "W...WWW...W", "W.........W", "WWWWWWWWWWW"],
             {"W": WHITE}),
    "heart": ([".RR...RR.", "RRRR.RRRR", "RRRRRRRRR", ".RRRRRRR.", "..RRRRR..", "...RRR...", "....R...."], {"R": RED}),
}


def icon(name, x=0, y=0, cv=None):
    cv = cv or Canvas()
    rows, pal = ICONS[name]
    cv.sprite(rows, x, y, pal)
    return cv


# --- media files --------------------------------------------------------------------------
def load_image(path):
    """Any picture -> 121 pixels: macOS's built-in `sips`, else ffmpeg (no Pillow needed)."""
    if not shutil.which("sips"):
        if not shutil.which("ffmpeg"):
            raise SystemExit("pictures need ffmpeg on this system (e.g. sudo apt install ffmpeg)")
        raw = subprocess.run(["ffmpeg", "-v", "error", "-i", path, "-vf", f"scale={SIZE}:{SIZE}:flags=area", "-frames:v", "1",
                              "-f", "rawvideo", "-pix_fmt", "rgb24", "-"], check=True, capture_output=True).stdout
        return [tuple(raw[i:i + 3]) for i in range(0, SIZE * SIZE * 3, 3)]
    with tempfile.TemporaryDirectory() as d:
        bmp = os.path.join(d, "x.bmp")
        subprocess.run(["sips", "-s", "format", "bmp", "-z", str(SIZE), str(SIZE), path, "--out", bmp],
                       check=True, capture_output=True)
        data = open(bmp, "rb").read()
    off, w, h, bpp = struct.unpack_from("<I", data, 10)[0], *struct.unpack_from("<iixxH", data, 18)
    step = bpp // 8
    stride = (w * step + 3) & ~3
    rows = range(abs(h)) if h < 0 else range(h - 1, -1, -1)
    out = []
    for y in rows:
        for x in range(w):
            b, g, r = data[off + y * stride + x * step: off + y * stride + x * step + 3]
            out.append((r, g, b))
    return out


def load_video(path, fps=5, max_frames=60):
    """GIF/MP4 -> list of frames via ffmpeg (only if ffmpeg is already installed)."""
    if not shutil.which("ffmpeg"):
        raise SystemExit("GIF/video needs ffmpeg (not installed). Still images work without it.")
    raw = subprocess.run(["ffmpeg", "-v", "error", "-i", path, "-vf", f"fps={fps},scale={SIZE}:{SIZE}:flags=area",
                          "-frames:v", str(max_frames), "-f", "rawvideo", "-pix_fmt", "rgb24", "-"],
                         check=True, capture_output=True).stdout
    n = SIZE * SIZE * 3
    return [[tuple(raw[i + j:i + j + 3]) for j in range(0, n, 3)] for i in range(0, len(raw) - n + 1, n)]


# --- text stored ON the box (0x49 animation, loops with the computer off) ---------------------
BOX_FRAMES = 40          # 40 proven; 100 frames made the stored animation freeze on playback (2026-10-27)
SPEEDS = {"slow": 1, "normal": 2, "fast": 3}     # px per frame; the box shows a frame every ~200 ms


def _clean(s):
    return " ".join("".join(ch for ch in s.upper() if ch in FONT).split())


def _wrap(words):
    """Up to 2 lines that each fit 11 px, or None."""
    lines = [""]
    for w in words:
        t = (lines[-1] + " " + w).strip()
        if text_width(t) <= SIZE:
            lines[-1] = t
        elif text_width(w) <= SIZE and len(lines) < 2:
            lines.append(w)
        else:
            return None
    return lines


def box_text(s, c=WHITE, speed="normal", max_frames=BOX_FRAMES):
    """Frames for a message stored on the box: one still frame if it fits on 1-2 lines, else a scroll
    trimmed to whole words so the loop fits max_frames. Returns (frames, shown_text, trimmed)."""
    c, step = color(c), SPEEDS.get(speed, 2)
    s = _clean(s)
    words = s.split()
    lines = _wrap(words) if words else None
    if lines:
        cv = Canvas()
        for n, ln in enumerate(lines):
            y = 3 if len(lines) == 1 else n * 6
            cv.text(ln, (SIZE - text_width(ln)) // 2, y, c)
        return [cv.pixels()], s, False
    fits = lambda t: len(range(0, text_width(t) + SIZE, step)) <= max_frames
    shown = s
    while len(words) > 1 and not fits(shown):
        words.pop()
        shown = " ".join(words)
    while shown and not fits(shown):                  # one giant word: cut letters
        shown = shown[:-1]
    w = text_width(shown)
    cv = Canvas(w + 2 * SIZE, SIZE)
    cv.text(shown, SIZE, 3, c)
    return [cv.window(x) for x in range(0, w + SIZE, step)], shown, shown != s
