"""Link to the box over Bluetooth classic (RFCOMM; channel from SDP, else the model's default).

macOS:          through the Timebox Bridge helper app (bridge/): macOS's /dev/cu.TimeBox-* serial port accepts
                writes but never delivers them, and Python on macOS has no Bluetooth sockets.
Linux/Windows:  Python's built-in Bluetooth socket (AF_BLUETOOTH / BTPROTO_RFCOMM), nothing to install.
"""
import os, re, select, socket, subprocess, sys, time
from . import proto

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
HOME = os.path.join(os.path.expanduser("~"), ".config", "timebox")
APP = os.path.join(ROOT, "bridge", "Timebox Bridge.app")
SOCK = os.path.join(HOME, "bridge.sock")
LOG = os.path.join(HOME, "bridge.log")
ADDR_FILE = os.path.join(HOME, "address")
MAC = sys.platform == "darwin"


def connect_bridge():
    if not os.path.exists(os.path.join(APP, "Contents", "MacOS", "tbridge")):
        subprocess.run([os.path.join(ROOT, "bridge", "build.sh")], check=True)
    for attempt in range(2):
        s = socket.socket(socket.AF_UNIX)
        try:
            s.connect(SOCK)
            return s
        except OSError:
            s.close()
            if attempt:
                break
            subprocess.run(["open", "-g", "-n", APP, "--stderr", LOG], check=True)
            for _ in range(40):
                time.sleep(0.25)
                if os.path.exists(SOCK):
                    break
    raise OSError(f"Timebox Bridge not reachable (see {LOG}); is the box paired and Connected?")


def find_address():
    """The box's Bluetooth address: TIMEBOX_ADDRESS env, ~/.config/timebox/address, or the paired-devices list."""
    a = os.environ.get("TIMEBOX_ADDRESS") or (open(ADDR_FILE).read().strip() if os.path.exists(ADDR_FILE) else "")
    if a:
        return a
    out = ""
    if sys.platform.startswith("linux"):
        out = subprocess.run(["bluetoothctl", "devices"], capture_output=True, text=True).stdout
    elif sys.platform == "win32":
        out = subprocess.run(["powershell", "-NoProfile", "-Command",
                              "Get-PnpDevice -Class Bluetooth | Where-Object FriendlyName -match 'timebox|pixoo|ditoo|tivoo|aurabox|divoom' | "
                              "Select-Object -ExpandProperty InstanceId"], capture_output=True, text=True).stdout
        m = re.search(r"DEV_([0-9A-F]{12})", out, re.I)
        if m:
            h = m[1]
            return ":".join(h[i:i + 2] for i in range(0, 12, 2))
    m = re.search(r"([0-9A-F]{2}(?::[0-9A-F]{2}){5})\s+(?:TimeBox|Pixoo|Ditoo|Tivoo|Aurabox|Divoom)", out, re.I)
    if m:
        return m[1]
    raise OSError("Timebox address not found: pair the box first, or save its address with "
                  "`tb address 11:22:33:44:55:66`")


def connect_rfcomm():
    if not hasattr(socket, "AF_BLUETOOTH"):
        raise OSError("this Python has no Bluetooth sockets (needs Linux with BlueZ, or Windows + Python 3.9+)")
    s = socket.socket(socket.AF_BLUETOOTH, socket.SOCK_STREAM, socket.BTPROTO_RFCOMM)
    s.settimeout(15)
    s.connect((find_address(), proto.model()["channel"]))
    s.settimeout(None)
    time.sleep(0.3)                 # the box greets with "HELLO"; drained by Timebox()
    return s


class Timebox:
    def __init__(self):
        self.sock = connect_bridge() if MAC else connect_rfcomm()
        self.sock.setblocking(False)
        self.fd = self.sock.fileno()

    def drain(self, wait=0.0):
        buf, end = b"", time.time() + wait
        while True:
            r, _, _ = select.select([self.fd], [], [], max(0, end - time.time()))
            if not r:
                return buf
            try:
                chunk = self.sock.recv(4096)
            except BlockingIOError:
                chunk = b""
            if not chunk:
                return buf
            buf += chunk

    def send(self, msg, pause=0.02):
        self.sock.setblocking(True)
        self.sock.sendall(msg)
        self.sock.setblocking(False)
        time.sleep(pause)
        self.drain()

    def query(self, msg, cmd, wait=1.5):
        """Send and return the payload of the box's reply to `cmd` (bytes after the 0x55 ack), or None."""
        self.drain()
        self.sock.setblocking(True); self.sock.sendall(msg); self.sock.setblocking(False)
        buf, end = b"", time.time() + wait
        while time.time() < end:
            buf += self.drain(0.1)
            for m in re.finditer(rb"\x01[^\x01\x02]*\x02", buf):
                u = proto.unframe(m.group())
                if u and u[0] == 0x04 and u[1][:2] == bytes([cmd, 0x55]):
                    return u[1][2:]
        return None

    def close(self):
        self.sock.close()

    # convenience
    def brightness(self, level):
        self.send(proto.brightness(level))

    def show(self, pixels):
        self.send(proto.image(pixels))
