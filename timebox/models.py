"""Which Divoom box we talk to. Everything is drawn at 11x11 (the Mini's size) and fitted to the real screen
when sent, so every feature works on every model. Only the Timebox Mini is tested on real hardware; the rest
follows hass-divoom's per-device code (docs/MODELS.md).

Pick a model:  TIMEBOX_MODEL env, `tb model <name>`, or automatic from the Bluetooth name."""
import json, os, re, subprocess, sys

HOME = os.path.join(os.path.expanduser("~"), ".config", "timebox")
MODEL_FILE = os.path.join(HOME, "model")

# size: screen pixels · family: "mini" (raw 12-bit pixels) / "aura" (8-colour nibbles) / "new" (palette images,
# Pixoo-generation commands) · escape: 01/02/03 byte escaping · channel: RFCOMM channel if SDP lookup fails
MODELS = {
    "timeboxmini": dict(name="Timebox Mini", size=11, family="mini", escape=True, channel=4, tested=True),
    "aurabox":     dict(name="Aurabox", size=10, family="aura", escape=True, channel=4),
    "timebox":     dict(name="Timebox Evo", size=16, family="new", escape=False, channel=1),
    "pixoo":       dict(name="Pixoo", size=16, family="new", escape=False, channel=1, no_volume=True),
    "pixoomax":    dict(name="Pixoo Max", size=32, family="new", escape=False, channel=1, no_volume=True),
    "ditoo":       dict(name="Ditoo", size=16, family="new", escape=False, channel=2),
    "tivoo":       dict(name="Tivoo", size=16, family="new", escape=False, channel=1),
    "backpack":    dict(name="Divoom Backpack", size=16, family="new", escape=False, channel=1, no_volume=True),
}
# Bluetooth name -> model, first match wins (names like "TimeBox-mini-audio", "Pixoo-Max", "Ditoo-Pro-light")
NAME_RULES = [("mini", "timeboxmini"), ("aura", "aurabox"), ("max", "pixoomax"), ("pixoo", "pixoo"),
              ("ditoo", "ditoo"), ("tivoo", "tivoo"), ("backpack", "backpack"), ("evo", "timebox"),
              ("timebox", "timebox")]
NAME_HINT = re.compile(r"timebox|pixoo|ditoo|tivoo|aurabox|backpack|divoom", re.I)


def from_name(name):
    n = (name or "").lower()
    for key, model in NAME_RULES:
        if key in n:
            return model
    return None


def paired_name():
    """The paired Divoom's Bluetooth name, or ''."""
    try:
        if sys.platform == "darwin":
            out = subprocess.run(["system_profiler", "-json", "SPBluetoothDataType"], capture_output=True, text=True, timeout=20).stdout
            bt = json.loads(out)["SPBluetoothDataType"][0]
            for group in ("device_connected", "device_not_connected"):
                for d in bt.get(group, []):
                    for name in d:
                        if NAME_HINT.search(name):
                            return name
        elif sys.platform.startswith("linux"):
            out = subprocess.run(["bluetoothctl", "devices"], capture_output=True, text=True, timeout=10).stdout
            m = re.search(r"Device \S+ (.*(?:%s).*)" % NAME_HINT.pattern, out, re.I)
            return m[1] if m else ""
    except Exception:
        pass
    return ""


def detect():
    """Model key: env > saved choice > Bluetooth name (cached) > Timebox Mini."""
    m = os.environ.get("TIMEBOX_MODEL")
    if not m and os.path.exists(MODEL_FILE):
        m = open(MODEL_FILE).read().strip()
    if not m:
        m = from_name(paired_name()) or "timeboxmini"
        try:
            os.makedirs(HOME, exist_ok=True)
            open(MODEL_FILE, "w").write(m)
        except OSError:
            pass
    return m if m in MODELS else "timeboxmini"


def save(m):
    if m not in MODELS:
        raise SystemExit("models: " + ", ".join(MODELS))
    os.makedirs(HOME, exist_ok=True)
    open(MODEL_FILE, "w").write(m)
