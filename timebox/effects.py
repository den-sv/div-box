"""Animations as generators of 121-pixel frames (streamed ~8 fps by the player)."""
import colorsys, math, random
from .gfx import Canvas, BLACK, WHITE, YELLOW, ORANGE, RED, GREEN, icon, text_or_scroll, ICONS
from .proto import SIZE

N = SIZE


def hsv(h, s=1.0, v=1.0):
    return tuple(int(c * 255) for c in colorsys.hsv_to_rgb(h % 1, s, v))


def rainbow(n=80):
    for t in range(n):
        yield [hsv((x + y) / 16 + t / 30) for y in range(N) for x in range(N)]


def fire(n=80):
    heat = [[0.0] * N for _ in range(N + 1)]
    for _ in range(n):
        heat[N] = [random.random() for _ in range(N)]
        for y in range(N):
            for x in range(N):
                below = heat[y + 1]
                heat[y][x] = max(0, (below[x] + below[(x - 1) % N] + below[(x + 1) % N]) / 3.1 - 0.04)
        yield [(min(255, int(h * 600)), int(max(0, h - 0.35) * 300), 0) for row in heat[:N] for h in row]


def matrix(n=80):
    drops = [random.randint(-N, 0) for _ in range(N)]
    for _ in range(n):
        cv = Canvas()
        for x in range(N):
            for tail in range(5):
                cv.set(x, drops[x] - tail, (0, max(0, 255 - tail * 60), 0) if tail else (180, 255, 180))
            drops[x] = drops[x] + 1 if drops[x] < N + 5 else random.randint(-6, 0)
        yield cv.pixels()


def life(n=80):
    g = {(random.randrange(N), random.randrange(N)) for _ in range(45)}
    hue = random.random()
    for t in range(n):
        yield [hsv(hue + t / 200) if (x, y) in g else BLACK for y in range(N) for x in range(N)]
        nb = {}
        for (x, y) in g:
            for dx in (-1, 0, 1):
                for dy in (-1, 0, 1):
                    if dx or dy:
                        k = ((x + dx) % N, (y + dy) % N); nb[k] = nb.get(k, 0) + 1
        new = {k for k, c in nb.items() if c == 3 or (c == 2 and k in g)}
        g = new if new and new != g else {(random.randrange(N), random.randrange(N)) for _ in range(45)}


def heart(n=40):
    for t in range(n):
        v = 0.45 + 0.55 * abs(math.sin(t / 3))
        rows, _ = ICONS["heart"]
        cv = Canvas(); cv.sprite(rows, 1, 2, {"R": (int(255 * v), 0, int(40 * v))})
        yield cv.pixels()


def fireworks(n=90):
    sparks = []
    for t in range(n):
        if t % 15 == 0:
            cx, cy, h = random.randint(2, 8), random.randint(2, 6), random.random()
            sparks += [[cx, cy, math.cos(a) * s, math.sin(a) * s, h, 1.0]
                       for a in [i * math.pi / 6 for i in range(12)] for s in (0.5, 0.9)]
        cv = Canvas()
        for p in sparks:
            cv.set(round(p[0]), round(p[1]), hsv(p[4], 0.7, p[5]))
            p[0] += p[2]; p[1] += p[3] + 0.08; p[5] *= 0.86
        sparks = [p for p in sparks if p[5] > 0.08]
        yield cv.pixels()


def sunrise(n=60):
    for t in range(n):
        k = t / n
        cv = Canvas(bg=(int(80 * k), int(40 * k), int(120 * (1 - k) + 60 * k)))
        sy = int(12 - 9 * k)
        for y in range(N):
            for x in range(N):
                if (x - 5) ** 2 + (y - sy) ** 2 <= 9:
                    cv.set(x, y, (255, int(120 + 120 * k), int(40 * k)))
        cv.rect(0, 9, N, 2, (20, 60 + int(80 * k), 20))
        yield cv.pixels()


def bell(n=24):
    for t in range(n):
        cv = Canvas()
        icon("bell", 2 + (1 if t % 4 < 2 else -1) * (t % 2), 2, cv)
        if t % 4 < 2:
            cv.set(0, 3, YELLOW); cv.set(10, 3, YELLOW)
        yield cv.pixels()


def spinner(n=40):
    ring = [(5 + round(4 * math.cos(a)), 5 + round(4 * math.sin(a))) for a in [i * math.pi / 8 for i in range(16)]]
    for t in range(n):
        cv = Canvas()
        for i in range(6):
            x, y = ring[(t + i) % 16]
            cv.set(x, y, hsv(t / 40, 1, (i + 1) / 6))
        yield cv.pixels()


def pacman(n=48):
    for t in range(n):
        cv = Canvas()
        px = (t % 16) - 3
        for d in range(0, N + 4, 4):
            if d > px + 3:
                cv.set(d, 5, WHITE)
        mouth = t % 4 < 2
        for y in range(N):
            for x in range(N):
                dx, dy = x - px, y - 5
                if dx * dx + dy * dy <= 9 and not (mouth and dx > 0 and abs(dy) <= dx):
                    cv.set(x, y, YELLOW)
        yield cv.pixels()


def blink_text(text, c=WHITE, times=3):
    frames = text_or_scroll(text, c)
    for _ in range(times):
        yield from frames
        if len(frames) == 1:
            yield from frames * 3
            yield from [Canvas().pixels()] * 2


EFFECTS = dict(rainbow=rainbow, fire=fire, matrix=matrix, life=life, heart=heart, fireworks=fireworks,
               sunrise=sunrise, bell=bell, spinner=spinner, pacman=pacman)
