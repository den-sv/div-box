# HANDOFF — read this first when continuing work

## State (2026-10-27)
Working on a real Timebox Mini (macOS): `tb` (bare = start + status + link + cheat sheet), `tb exit`, dashboard,
voice, stocks, weather, rotation, Mac alarms/reminders/timer, box alarms (silent or 1-16, flash clock or the box's
built-in alarm animation), message stored on the box (`tb boxtext`, ≤40 frames). Dashboard = aligned card columns
(top row "on the box", rest "from the Mac"); box alarms: edit a slot, press its save (shows ● when changed); "↻ read from box" reloads them.
Auto rotation: "apply" saves rotation + base + night in one request; "▶ try" saves, then plays the ticked items once
(daemon cmd `rotate-now`).
All config edits (dashboard + daemon) go through `app.edit_lock`: before 2026-10-27 two saves at once undid each other
(rotation checkboxes "didn't save").
Other Divoom models: written from hass-divoom, untested (docs/MODELS.md). Linux/Windows: written, untested.
Repo is PRIVATE; README/CONTRIBUTING/NOTICE/issue templates are written for going public. History was squashed to one
clean commit on 2026-10-28 (full old history kept locally only: private/history-backup.bundle). Going public = owner's call.
Owner's box: never use sound in tests (silent alarms only).

## Cross-platform (2026-10-26)
- macOS = bridge app (tested). Linux/Windows = stdlib `socket.AF_BLUETOOTH/BTPROTO_RFCOMM` to (address, 4) in
  `device.connect_rfcomm`; address from TIMEBOX_ADDRESS, ~/.config/timebox/address (`tb address`), bluetoothctl / PnP.
  Written + simulated on macOS (sys.platform patched), NOT yet tested on real Linux/Windows hardware.
- CLI → service now goes over the dashboard HTTP API (`app.send_to_daemon`), no unix socket (Windows-safe).
- Voice off-Mac: espeak-ng / PowerShell SAPI → WAV → hum + play on the default output (box must be default speaker).
- Images off-Mac: ffmpeg instead of sips. Entry points: `bin/tb` (mac/linux), `tb.py`, `python -m timebox`.

## Architecture in one breath
`tb` (Python stdlib) → unix socket `~/.config/timebox/bridge.sock` → `Timebox Bridge.app` (Swift/IOBluetooth,
built by `bridge/build.sh`, gitignored) → RFCOMM channel from SDP (Mini: 4) → box.
The service (`tb start`, `timebox/app.py:daemon`) owns the link and also serves the dashboard on 127.0.0.1:8411
(`timebox/web.py`, page `timebox/ui.html`). With no service running, one-off CLI commands talk to the bridge directly.
Only one process may hold the bridge at a time (the CLI routes through the service's HTTP API when it is up).

## Hard-won facts (don't re-learn these)
- `/dev/cu.TimeBox-mini-audio` is useless on macOS 12+: writes queue in the driver and are never sent (TIOCOUTQ stays >0).
  Clearing CRTSCTS doesn't help. Don't go back there.
- `openRFCOMMChannelSync` → kIOReturnError (-536870212). `openRFCOMMChannelAsync` works. Keep async.
- A bare CLI binary using IOBluetooth is SIGABRTed by TCC (exit 134) when launched from a terminal or app
  without a Bluetooth usage string. Hence the `.app` with `NSBluetoothAlwaysUsageDescription`, launched via `open`.
- The box sends `00 05 48 45 4C 4C 4F 00` ("HELLO") on connect and ACKs commands as `01 06 00 04 <cmd> 55 … 02`.
- Changing the bundle id / re-signing the bridge may make macOS ask for Bluetooth permission again.
- Images: 4 bits per channel, low nibble first, 182 bytes per 11×11 frame; bytes 01/02/03 must be escaped (see docs/PROTOCOL.md).
- **Stored text** (`tb boxtext`, dashboard "store text"): `gfx.box_text` renders a message into the single stored
  animation slot. Fits on 2 lines of ≤11 px (e.g. "HI MOM") → 1 still frame; else scroll 1/2/3 px per ~200 ms frame,
  trimmed to whole words so it fits `box.max_frames` (default `gfx.BOX_FRAMES` = 40).
- **Silent box alarm = mode 0A + volume byte 0** (verified twice 2026-10-27, box volume irrelevant). Mode `00` is
  "Bluetooth music": the box sends PLAY (Music.app opened on the Mac) and beeps if nothing plays. Never send 00.
  Trigger 04 is the box's BUILT-IN alarm animation, not our uploaded one (the owner watched twice 2026-10-27 with
  "HELLO TEST" stored: alarm showed the built-in flashing GIF). An alarm can't show custom content without the Mac.
- **Capacity test 2026-10-27:** 100 stored frames (delay 3) → when an alarm played them the screen froze on one frame
  (box still answered Bluetooth; `boxalarm off` + `clock` recovered it, no pinhole). 40 frames work. Keep ≤40;
  the real limit is somewhere 40-99, untested. `0x45 03` shows a BUILT-IN line animation, not the stored one.
- Streaming ~8 fps of static `0x44` images is smooth. On-box animation (`0x49`, `tb upload`) loops by itself; the
  delay unit is ~200 ms.

## ⚠️ FREEZES THE BOX (needs pinhole reset) — never send
- `0x61` set radio frequency (bytes [f10%100, f10//100], format confirmed by reading `0x60`) → box went silent. Radio removed.
- Blind opcode probing (0x40-0x76 without args) → froze it once. For box-side alarms, capture the Divoom app's traffic
  (Android HCI snoop log), never guess.
- Verified safe + ACKed: 0x09 get volume (→ value), 0x08 set volume, 0x0B get mute, 0x05 radio on/off, 0x44, 0x74, 0x18,
  0x45 views 00 clock / 01 temp (sub 01 = °F) / 02 off / 04 visualizer / 06 stopwatch.
- The box beeps every hour by itself (built-in hourly chime). No known command turns it off; needs a capture of the Divoom app.

## Voice & sound (verified by ear 2026-10-26)
- ffmpeg lists the box TWICE: `TimeBox-mini-audio …:input` (HFP mic) and `…:output`. Match `:output` or nothing plays.
- The box's volume command (0x08) does NOT change Bluetooth audio loudness → volume is applied as gain to our audio
  (`sound.GAIN` = audio.volume/16; mute = 0).
- The box AUTO-MUTES its amp on silence and needs ~1 s to reopen: words get clipped. Leading digital silence, keep-alive
  zero streams and -66 dB hiss all failed. What works: one persistent PCM stream (`sound.Speaker`, ffmpeg stdin →
  audiotoolbox) + a 30 Hz hum (`wake_tone`, ~400 ms, inaudible on the tiny driver) spliced before every speech/sound.
- Speech: `say -o file.aiff` → rendered to PCM → spliced into the stream. Fallbacks: one-shot ffmpeg, then Mac speakers.

## Box alarms (verified 2026-10-26)
0x42 read / 0x43 write, 3 slots × 10 bytes (see docs/PROTOCOL.md §8). Mode 00 = flash, 0A = ring. Weekday mask bit0 = MONDAY (verified). Alarm volume byte 0-100 (2-5 quiet); tb/dashboard show it as 0-16 like the box volume.
Remote stop: A5 00 00 00 alone was unreliable, so stop-ring now also re-saves (off, then on) any alarm that went off in the
last 5 min. Confirmed by eye 2026-10-27 (silent flash-clock alarm stopped 15 s in). Mac-side extras (text/picture/voice) play 2 s AFTER the
alarm starts: they show over a FLASH alarm, a RINGING box hides them. `tb boxalarm`, dashboard "BOX ALARMS".
private/divoom_official_bluetooth.md = Divoom's OFFICIAL BT docs (92 pages, newer gen). Tried on the Mini 2026-10-28,
results in docs/PROTOCOL.md (end): scoreboard ✅ (tb score), memorial ✅ but plays music (not used), alarm GIF 0x51 ❌, countdown ❌.
The box still holds an old app memorial in slot 0: leave it. Firmware update: NOT attempted, never (no Mini image exists). NEVER: 0x27 BT PIN, 0x8B, 0x75, 0xAB, 0xB2, 0x52, 0xB1/B6.
private/RESEARCH.md (gitignored, NOT public: it cites decompiled-app sources) = full opcode research. Next candidates to decode: the 0x46 settings block
(change one setting, re-read, diff). Hourly beep has no known command (no known opcode).

## Unverified / ideas
- Mute byte polarity (`0x0A`: 00 = mute) is from docs; get-mute returned 00 while sound was audible, so it may be inverted.
- Ideas: macOS notification mirroring (needs Full Disk Access, deliberately skipped), calendar next-event,
  CPU/battery meter, scoreboard view (`0x45 07`), per-frame GIF timing.

## Test checklist after changes
`tb status` · `tb text HI` · `tb weather` · `tb stock NVDA` · `tb ui` (click an animation; the live preview should move) ·
switch the box off/on → `tb status` shows `bluetooth : up` again within ~10 s · `python3 tools/previews.py` for README images.

## Other Divoom models (2026-10-27)
`timebox/models.py` = per-model profiles + auto-detect from the BT name (cached in ~/.config/timebox/model, `tb model`).
`proto.py` dispatches on `proto.model()["family"]` (mini / aura / new). Content stays 11x11; `proto.fit()` adapts to
the screen. Use `proto.animation(frames)` (not anim_frame) to store animations. Mini bytes are unchanged (checked).
Everything non-Mini is untested and comes from hass-divoom; details in docs/MODELS.md. The macOS bridge source now
matches any Divoom name, but the owner's built app was NOT rebuilt (rebuilding re-asks Bluetooth permission).

Screens (2026-10-28, owner's rule): NOTHING scrolls on the Mac-side jobs. Every screen is a still card of max two
~3-letter lines (gfx.card / gfx.pages), shown gfx.PAGE s (rotation.page_secs, default 2; dashboard "sec per screen", `tb set --page 3`; build() sets it). Stocks = [ticker] + [price / change%], weather = one screen
[CITY / 12C], date = [OCT / 28]. Only `boxtext` (stored on the box) may scroll.
