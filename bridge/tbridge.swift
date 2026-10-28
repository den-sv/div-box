// Timebox Bridge: owns the RFCOMM link to the Timebox (Apple IOBluetooth only) and exposes it as a
// local unix socket ~/.config/timebox/bridge.sock. Bytes in -> box, box -> bytes out. One client at a time.
// Runs as a tiny .app so macOS grants it Bluetooth permission. The /dev/cu.* serial port that macOS
// creates for the box accepts writes but never sends them, hence this.
import Foundation
import IOBluetooth

func log(_ s: String) { FileHandle.standardError.write(("[bridge] " + s + "\n").data(using: .utf8)!) }

let home = NSHomeDirectory() + "/.config/timebox"
let sockPath = home + "/bridge.sock"
let addrFile = home + "/address"
try? FileManager.default.createDirectory(atPath: home, withIntermediateDirectories: true)

func findDevice() -> IOBluetoothDevice? {
    if let a = try? String(contentsOfFile: addrFile, encoding: .utf8).trimmingCharacters(in: .whitespacesAndNewlines),
       !a.isEmpty, let d = IOBluetoothDevice(addressString: a) { return d }
    for d in (IOBluetoothDevice.pairedDevices() ?? []) {
        if let dev = d as? IOBluetoothDevice,
           ["timebox", "pixoo", "ditoo", "tivoo", "aurabox", "divoom"].contains(where: { (dev.name ?? "").lowercased().contains($0) }) { return dev }
    }
    return nil
}

final class Link: NSObject, IOBluetoothRFCOMMChannelDelegate {
    var channel: IOBluetoothRFCOMMChannel?
    var client: Int32 = -1
    let opened = DispatchSemaphore(value: 0)

    var opening = false
    var lastFail = Date.distantPast
    var openStarted = Date.distantPast

    // main thread: start an async open unless one is running
    func startOpen() {
        if channel?.isOpen() ?? false { return }
        // an async open can silently never complete while the box is off: give up after 20 s and retry
        if opening && Date().timeIntervalSince(openStarted) < 20 { return }
        guard let dev = findDevice() else { log("no paired Timebox"); lastFail = Date(); return }
        var chID: BluetoothRFCOMMChannelID = 4
        if let rec = dev.getServiceRecord(for: IOBluetoothSDPUUID(uuid16: 0x1101)) {
            var c: BluetoothRFCOMMChannelID = 0
            if rec.getRFCOMMChannelID(&c) == kIOReturnSuccess { chID = c }
        }
        var ch: IOBluetoothRFCOMMChannel?
        opening = true; openStarted = Date()
        if dev.openRFCOMMChannelAsync(&ch, withChannelID: chID, delegate: self) != kIOReturnSuccess {
            opening = false; lastFail = Date()
        }
    }

    // background thread: true when the box is reachable; waits briefly for a fresh connect,
    // but answers instantly while the box is known to be off so callers never stall
    func ensureOpen() -> Bool {
        let (up, recentFail) = DispatchQueue.main.sync { (channel?.isOpen() ?? false, Date().timeIntervalSince(lastFail) < 5) }
        if up { return true }
        if recentFail { return false }
        while opened.wait(timeout: .now()) == .success {}
        DispatchQueue.main.async { self.startOpen() }
        _ = opened.wait(timeout: .now() + 8)
        return DispatchQueue.main.sync { channel?.isOpen() ?? false }
    }

    func setState(_ up: Bool) {
        try? (up ? "up" : "down").write(toFile: home + "/link", atomically: true, encoding: .utf8)
    }

    func rfcommChannelOpenComplete(_ ch: IOBluetoothRFCOMMChannel!, status: IOReturn) {
        opening = false
        if status == kIOReturnSuccess { channel = ch; log("connected, mtu \(ch.getMTU())"); setState(true) }
        else { lastFail = Date(); log("open failed \(status)") }
        opened.signal()
    }

    func write(_ data: [UInt8]) {
        guard ensureOpen() else { return }
        DispatchQueue.main.sync {
            guard let ch = channel else { return }
            var bytes = data
            let mtu = max(1, Int(ch.getMTU()))
            var i = 0
            while i < bytes.count {
                let n = min(mtu, bytes.count - i)
                let off = i
                let rc = bytes.withUnsafeMutableBytes { ch.writeSync($0.baseAddress! + off, length: UInt16(n)) }
                if rc != kIOReturnSuccess { log("write failed \(rc)"); channel = nil; return }
                i += n
            }
        }
    }

    func rfcommChannelData(_ ch: IOBluetoothRFCOMMChannel!, data p: UnsafeMutableRawPointer!, length n: Int) {
        if client >= 0 { _ = Foundation.write(client, p, n) }
    }
    func rfcommChannelClosed(_ ch: IOBluetoothRFCOMMChannel!) { log("link closed"); channel = nil; setState(false) }
}

let link = Link()
link.setState(false)
// reconnect watchdog: the box drops the link when switched off; reopen as soon as it's back
Timer.scheduledTimer(withTimeInterval: 5, repeats: true) { _ in link.setState(link.channel?.isOpen() ?? false); link.startOpen() }
unlink(sockPath)
let srv = socket(AF_UNIX, SOCK_STREAM, 0)
var sa = sockaddr_un(); sa.sun_family = sa_family_t(AF_UNIX)
withUnsafeMutableBytes(of: &sa.sun_path) { buf in
    sockPath.utf8CString.withUnsafeBytes { src in buf.copyMemory(from: UnsafeRawBufferPointer(rebasing: src.prefix(buf.count))) }
}
guard withUnsafePointer(to: &sa, { $0.withMemoryRebound(to: sockaddr.self, capacity: 1) { bind(srv, $0, socklen_t(MemoryLayout<sockaddr_un>.size)) } }) == 0
else { log("bind failed"); exit(1) }
chmod(sockPath, 0o600)
listen(srv, 4)
log("listening on \(sockPath)")

Thread {
    _ = link.ensureOpen()
    while true {
        let c = accept(srv, nil, nil)
        if c < 0 { continue }
        DispatchQueue.main.sync { link.client = c }
        var buf = [UInt8](repeating: 0, count: 4096)
        while true {
            let n = read(c, &buf, buf.count)
            if n <= 0 { break }
            link.write(Array(buf[0..<n]))
        }
        DispatchQueue.main.sync { link.client = -1 }
        close(c)
    }
}.start()
RunLoop.main.run()
