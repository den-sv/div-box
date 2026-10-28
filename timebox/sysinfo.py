"""Mac + box stats for the 'sys' screen and the dashboard (stdlib + built-in macOS tools)."""
import datetime as dt, json, os, re, shutil, subprocess, time
from . import models
from . import gfx
from .gfx import Canvas, text_width, scroll_frames, card, GREEN, CYAN, YELLOW, ORANGE, RED


def _run(*cmd):
    try:
        return subprocess.run(cmd, capture_output=True, text=True, timeout=8).stdout.strip()
    except Exception:
        return ""


def _human(sec):
    d, rem = divmod(int(sec), 86400)
    h, m = divmod(rem // 60, 60)
    return f"{d}d {h}h" if d else f"{h}h {m}m"


def mac():
    total = int(_run("sysctl", "-n", "hw.memsize") or 0)
    vm = _run("vm_stat")
    page = int(re.search(r"page size of (\d+)", vm)[1]) if "page size" in vm else 16384
    pages = {k.strip(): int(v.strip(" .")) for k, v in re.findall(r"^(.+?):\s+(\d+)\.?$", vm, re.M)}
    used = (pages.get("Pages active", 0) + pages.get("Pages wired down", 0) + pages.get("Pages occupied by compressor", 0)) * page
    boot = int(re.search(r"sec = (\d+)", _run("sysctl", "-n", "kern.boottime"))[1])
    cores = os.cpu_count() or 1
    cpu = sum(float(x) for x in _run("ps", "-A", "-o", "%cpu=").split() if x) / cores
    du = shutil.disk_usage("/")
    batt = _run("pmset", "-g", "batt")
    bm = re.search(r"(\d+)%", batt)
    return {
        "model": _run("sysctl", "-n", "hw.model"),
        "chip": _run("sysctl", "-n", "machdep.cpu.brand_string"),
        "cores": cores,
        "macos": _run("sw_vers", "-productVersion"),
        "host": _run("scutil", "--get", "ComputerName"),
        "uptime": _human(time.time() - boot),
        "load": " ".join(f"{x:.2f}" for x in os.getloadavg()),
        "cpu": round(min(100, cpu)),
        "ram": round(100 * used / total) if total else 0,
        "ram_gb": round(total / 2**30),
        "disk": round(100 * du.used / du.total),
        "disk_free_gb": round(du.free / 2**30),
        "battery": int(bm[1]) if bm else None,
        "power": "AC" if "AC Power" in batt else "battery",
    }


def box():
    import sys
    if sys.platform != "darwin":
        link = os.path.join(os.path.expanduser("~"), ".config", "timebox", "link")
        up = os.path.exists(link) and open(link).read().strip() == "up"
        return {"name": models.MODELS[models.detect()]["name"], "connected": up}
    try:
        d = json.loads(_run("system_profiler", "SPBluetoothDataType", "-json"))
        for ctl in d.get("SPBluetoothDataType", []):
            for state in ("device_connected", "device_not_connected"):
                for entry in ctl.get(state, []):
                    for name, v in entry.items():
                        if models.NAME_HINT.search(name):
                            return {"name": name, "connected": state == "device_connected",
                                    "address": v.get("device_address"), "battery": v.get("device_batteryLevelMain"),
                                    "rssi": v.get("device_rssi"), "type": v.get("device_minorType"),
                                    "services": v.get("device_services"), "firmware": v.get("device_firmwareVersion")}
    except Exception:
        pass
    return {}


def bars_frame(m):
    """Four meters: CPU, RAM, DISK, BATTERY (2 px wide each), height = %."""
    cv = Canvas()
    vals = [(m["cpu"], GREEN), (m["ram"], CYAN), (m["disk"], YELLOW), (m["battery"] if m["battery"] is not None else 100, ORANGE)]
    for i, (v, col) in enumerate(vals):
        h = max(1, round(11 * v / 100))
        x = i * 3
        for y in range(11 - h, 11):
            hot = RED if v >= 90 and i < 3 else col
            cv.set(x, y, hot); cv.set(x + 1, y, hot)
    return cv.pixels()


def job(m=None):
    m = m or mac()
    c = (120, 255, 160)                        # still screens, 2 s each: CPU / 12%, RAM / 48% ...
    cards = [card(k, f"{min(int(m[key]), 99)}%", CYAN, c) for k, key in (("CPU", "cpu"), ("RAM", "ram"), ("DSK", "disk"))]
    if m["battery"] is not None:
        cards.append(card("BAT", f"{min(int(m['battery']), 99)}%", CYAN, c))
    return [(bars_frame(m), gfx.PAGE)] + [(f, gfx.PAGE) for f in cards]
