"""Live data with no API keys: Open-Meteo weather, Yahoo/Stooq quotes. stdlib urllib only."""
import csv, io, json, re, urllib.parse, urllib.request
from .gfx import Canvas, icon, CYAN, WHITE, GREEN, RED, ORANGE, text_width, card, fit_word
from .proto import SIZE

UA = {"User-Agent": "Mozilla/5.0 (Macintosh) div-box/1.0"}


def get(url, timeout=10):
    with urllib.request.urlopen(urllib.request.Request(url, headers=UA), timeout=timeout) as r:
        return r.read()


def weather(lat, lon):
    q = urllib.parse.urlencode(dict(latitude=lat, longitude=lon, current="temperature_2m,weather_code,is_day",
                                    daily="temperature_2m_max,temperature_2m_min", timezone="auto", forecast_days=1))
    d = json.loads(get("https://api.open-meteo.com/v1/forecast?" + q))
    c = d["current"]
    return dict(temp=round(c["temperature_2m"]), code=c["weather_code"], day=c["is_day"],
                hi=round(d["daily"]["temperature_2m_max"][0]), lo=round(d["daily"]["temperature_2m_min"][0]))


def weather_icon(code):
    if code in (0, 1): return "sun"
    if code == 2: return "partly"
    if code == 3: return "cloud"
    if code in (45, 48): return "fog"
    if 71 <= code <= 77 or code in (85, 86): return "snow"
    if code >= 95: return "storm"
    return "rain"


def temp_color(t):
    return CYAN if t <= 0 else WHITE if t < 15 else ORANGE if t < 27 else RED


def weather_frame(w):
    cv = Canvas()
    icon(weather_icon(w["code"]), 0, 0, cv)
    s = f"{w['temp']}°" if text_width(f"{w['temp']}°") <= SIZE else str(w["temp"])
    cv.text(s, (SIZE - text_width(s)) // 2, 6, temp_color(w["temp"]))
    return cv.pixels()


def quote(symbol):
    """-> (price, change_pct). Yahoo chart API first, Stooq CSV as fallback."""
    try:
        d = json.loads(get(f"https://query1.finance.yahoo.com/v8/finance/chart/{urllib.parse.quote(symbol)}?range=1d&interval=1d"))
        m = d["chart"]["result"][0]["meta"]
        price, prev = m["regularMarketPrice"], m.get("chartPreviousClose") or m.get("previousClose")
        return price, (price - prev) / prev * 100
    except Exception:
        s = symbol.lower() if "." in symbol else symbol.lower() + ".us"
        row = next(csv.DictReader(io.StringIO(get(f"https://stooq.com/q/l/?s={s}&f=sd2t2ohlcv&h&e=csv").decode())))
        price, open_ = float(row["Close"]), float(row["Open"])
        return price, (price - open_) / open_ * 100


def fmt_price(p):
    return f"{p:.0f}" if p >= 100 else f"{p:.1f}" if p >= 10 else f"{p:.2f}"


def short_price(p):
    """Price in 11 px (3 characters): 406 · 41 · 4.1 · .52 · 67K · 2K · 1M"""
    for div, suf in ((1e6, "M"), (1e3, "K")):
        if p >= div:
            return f"{p / div:.0f}{suf}"
    if p >= 10:
        return f"{p:.0f}"
    return f"{p:.1f}" if p >= 1 else f"{p:.2f}".lstrip("0")


def short_pct(pct):
    """Change in 11 px: 1.5 (one decimal under 10 %), else 12% / 99%. Green = up, red = down."""
    a = abs(pct)
    return f"{a:.1f}" if a < 9.95 else f"{min(round(a), 99)}%"


def stock_cards(symbol, price, pct):
    """Two still screens: ticker (two lines when it's 4+ letters), then price over % change."""
    c = GREEN if pct >= 0 else RED
    sym = re.split(r"[-.=^]", symbol.upper().lstrip("^"))[0] or symbol.upper()
    if text_width(sym) <= SIZE:
        first = card(sym, None, WHITE)
    else:
        half = (len(sym) + 1) // 2
        first = card(fit_word(sym[:half]), fit_word(sym[half:]), WHITE)
    return [first, card(short_price(price), short_pct(pct), WHITE, c)]


def weather_cards(w, city):
    """One screen: CITY (first letters that fit) over the temperature, e.g. ETO / 12C."""
    t = w["temp"]
    ts = f"{t}C" if text_width(f"{t}C") <= SIZE else str(t)
    return [card(fit_word(re.sub(r"[^A-Za-z]", "", city) or "?"), ts, CYAN, temp_color(t))]
