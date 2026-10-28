# Divoom Timebox Mini - Bluetooth RFCOMM/SPP protocol

Compiled 2026-10-26 from reading source on GitHub (nothing cloned or run against hardware).
Hex examples marked **[computed]** were produced by re-implementing the framing rules below, not copied
from a repo; everything else cites file:line. Unverified inferences are marked **[inferred]**.

Repo keys (line numbers are from `raw.githubusercontent.com` at default branch, 2026-10-26):

| Key | Repo | Branch | Files used |
|---|---|---|---|
| **J** | jbfuzier/timeboxmini | master | `doc/protocol.md`, `package/messages.py`, `package/timebox.py`, `package/divoom_image.py`, `package/timeboximage.py`, `package/timebox_mqtt_daemon.py` |
| **S** | Smanar/timebox | master | `timebox.py`, `messages.py` (byte-identical to J's, diff empty), `README.md` |
| **H** | mathoudebine/homeassistant-timebox-mini | main | `custom_components/timebox_mini/__init__.py`, `timebox.py`, `README.md` |
| **D** | derHeinz/divoom-adapter | master | `divoom_protocol.py`, `divoom_device.py`, `readme.md`, `divoom_image.py` (this is the **Aurabox**, 10x10, not the Mini) |
| **E** | RomRider/node-divoom-timebox-evo | master | `PROTOCOL.md` (Evo only) |

## Official docs

Divoom publishes developer docs, including a Bluetooth section for tivoo/timebox/pixoo/backpack:
<https://docin.divoom-gz.com/web/#/5/146>. They describe the newer generation; nothing there is confirmed for the
Mini, so everything below still comes from testing our own box. Not copied here (no license stated).

## 0. Licenses

| Repo | License | Evidence |
|---|---|---|
| J jbfuzier/timeboxmini | **None** (no LICENSE file, GitHub API `license: null`) | repo tree listing; so legally "all rights reserved" |
| S Smanar/timebox | **None** (no LICENSE file, `license: null`) | repo tree listing |
| H homeassistant-timebox-mini | **GPL-3.0** | `LICENSE`, GitHub API spdx `GPL-3.0` |
| D derHeinz/divoom-adapter | **GPL-3.0** (repo archived 2025-02-03) | `LICENSE` |
| E node-divoom-timebox-evo | **MIT** | `LICENSE.md` |

Implication: write our own implementation from this spec; do not paste code from J/S (unlicensed) or H/D (GPL-3.0).
The wire format itself is a fact, not code.

## 1. Transport and framing

### 1.1 Transport
- Classic Bluetooth, **RFCOMM channel 4**, SPP. J `doc/protocol.md:6`; `package/timebox.py:86` (`connect(host, port=4)`);
  H `timebox.py:18` (`self.sock.connect((self.addr, 4))`); S `timebox.py:158`; D `divoom_device.py:10`.
- Must be paired first (H README:113-143 `bluetoothctl ... pair <MAC>`). MACs of the Mini start `11:75:58` (examples in J `timebox.py:215`, S `:30`, H README:126).
- Audio is a **separate** Bluetooth profile (A2DP) - S plays sound by `aplay`/`mpg123` to bluealsa, not via RFCOMM (S `timebox.py:109-121`). RFCOMM only does display/control/volume/radio.

### 1.2 Greeting sent by the device on connect
- Device sends unframed `00 05 48 45 4C 4C 4F 00` ("\0\5HELLO\0"). J `protocol.md:7-8, 29`; H `__init__.py:15-16` (`TIMEBOX_HELLO = [0, 5, 72, 69, 76, 76, 79, 0]`);
  S `timebox.py:50-52` (reads 256 bytes after connect and compares to HELLO).
- It does **not** start with 0x01, so a parser must skip garbage until 0x01 (J `timebox.py:147-170` `has_message/remove_garbage`).

### 1.3 Message layout (host -> device and device -> host)
```
01  [ payload (escaped) ]  [ checksum lo, hi (escaped) ]  02
payload = LEN_lo LEN_hi  CMD  ARGS...
```
- Start byte `0x01`, end byte `0x02`. J `protocol.md:12-13`; J `messages.py:62`.
- **Length** = 2 bytes **little-endian** (LSB first). It counts **the two length bytes + the command byte + args**
  (i.e. the whole unescaped payload), and excludes checksum, start/end. Code: `length = len(args)+3` where `args` excludes cmd (J `timebox.py:137`; S `:215`).
  Proof: `05 00 45 00 01` has length 5 for cmd+2 args (J `protocol.md:22-23`); static image `BD 00 44 ...` = 0xBD = 189 = 2+1+4+182 (J `messages.py:68`, `protocol.md:46`).
  Evo defines it identically (E:69: payload without LLLL + 2 CRC bytes).
- **Checksum** = arithmetic sum (mod 65536) of **all unescaped payload bytes including the length bytes**, stored **little-endian**:
  `lo = sum & 0xFF`, `hi = sum >> 8`. J `messages.py:6-11`; `protocol.md:17-18`; H `__init__.py:91-94`; D `divoom_protocol.py:101-105`.
  Checksum is computed **before** escaping; the two checksum bytes are then escaped themselves like any byte (J `messages.py:53-62`; H `:101`, `:223`; D `:114-119`).
- **Escaping** (applies to payload AND checksum bytes, never to the framing 01/02): `01 -> 03 04`, `02 -> 03 05`, `03 -> 03 06`
  (i.e. `03, b+3` for b in {1,2,3}). J `protocol.md:15-16`; `messages.py:13-21`; H `__init__.py:76-88`; D `divoom_protocol.py:13-15, 26-36`.
  Unescape: on `03`, next byte must be 04..06, subtract 3 (J `messages.py:23-38`). Receiving also validates checksum (`:40-51`).
- Worked example copied from J `protocol.md:23`: clock command payload `05 00 45 00 01`, sum = 0x4B, message `01 05 00 45 00 03 04 4B 00 02`
  (the data byte `01` became `03 04`). **[computed]** reproduces it exactly.

### 1.4 Device -> host responses
- Same framing. Payload: `LEN_lo LEN_hi 04 CMD 55 [data]`. The 3rd byte "always 0x04", 5th "always 0x55" = ACK. J `protocol.md:26-27`.
  E agrees: `01 LLLL 04 CC 55 PAYLOAD CRCR 02` (E:379-392).
- Example: get-volume reply `06 00 04 09 55 XX` (J `protocol.md:38`).
- Malformed command -> NAK `XX AA` where XX is the command number (J `protocol.md:28`).
- Device also pushes unsolicited messages, e.g. `0x59` temperature changes (J `protocol.md:61-62`).
- Not all commands are acknowledged-with-data; H calls `sock.recv(256)` after each send (H `timebox.py:34-36`) and skips it for non-final animation frames (H `__init__.py:279-284`).

## 2. Commands (CMD byte = first byte after length)

Table from J `protocol.md:31-66` + J `timebox.py:28-41` + S `timebox.py:85-98` + H `__init__.py:33-42, 97-124, 309-328`.
All "message" hex below is **[computed]** with the framing above unless a cite is given.

| CMD | Name | Args | Notes / source |
|---|---|---|---|
| `05` | radio on/off | `00` off / `01` on | `04 00 05 01` (J pm:34) |
| `08` | set volume | `00..10` (0x10 = 16 max) | `04 00 08 03` (J pm:36); H `__init__.py:309-314` default 4 |
| `09` | get volume | none | `03 00 09` -> reply `06 00 04 09 55 XX` (J pm:38) |
| `0A` | set mute | `00` mute / `01` unmute | J pm:39-40 |
| `0B` | get mute | none | J pm:41 |
| `18` | set date/time | see 2.2 | |
| `44` | static image | see 3 | |
| `45` | switch view | see 2.1 | |
| `49` | animation frame | see 4 | |
| `59` | temperature report | device -> host, unsolicited | J pm:61-62 |
| `60` | get radio freq | reply 2 bytes `XX YY` = YX.X MHz (`03 0A` = 100.3) | J pm:63-64 |
| `61` | set radio freq | same encoding | J pm:65-66 |
| `74` | set brightness | 1 byte; HA default 50 | H `__init__.py:120-124, 325-328`. Range for Mini not stated in code; Evo uses 0-100 (E:122-133). |

(pm = `doc/protocol.md` line.)

Not found for the Mini in any repo: **alarm, notification sounds, scoreboard score payload, weather payload, text command.**
- Text is rendered client-side to a wide 11-px-high image and scrolled by sending successive static images (`sleep(1/speed)` between) or as animation frames
  (J `timebox.py:51-78`, `divoom_image.py:112-146`; the dynamic version "cannot go faster than 1fps", `timebox.py:66`).
- Weather: H README says weather display requires the Divoom phone app to send the data (README grep line 32); H's "weather" action is only the temperature view with a color (`__init__.py:289-297`).
- Alarm: nothing in any repo.

### 2.1 Switch view `45`
Args: `VIEW [sub] [R G B [X]]`. J `protocol.md:49-57`; H `__init__.py:33-42`; S `timebox.py:273-296`.

| VIEW | Meaning | Source |
|---|---|---|
| `00` | clock; sub `00` = 12h, `01` = 24h; optional RGB | J pm:55, H:98 (`0x01 if h24 else 0x00`) |
| `01` | temperature; sub `00` = Celsius, `01` = Fahrenheit; optional RGB | J pm:51-54, H:106 |
| `02` | off | H:36 `"off": 0x02`; S `timebox.py:287-290` sends `45 02 00` |
| `03` | animation | H:37 (name only) |
| `04` | "graph" (probably visualizer/spectrum) | H:38 name only; **[inferred]** |
| `05` | "image" | H:39 name only |
| `06` | stopwatch (S sends sub `01` = start, comment "00 : off, 01 : start counter") | J pm:56, S `:292-296` |
| `07` | scoreboard | J pm:57, H:41 |

Hex messages **[computed]**:
- Clock 24h: `01 05 00 45 00 03 04 4B 00 02` (matches J pm:23).
- Clock 12h red: `01 08 00 45 00 00 FF 00 00 4C 03 04 02` (sum 0x14C -> `4C 01`, the `01` is escaped to `03 04`).
- Temp C: `01 05 00 45 03 04 00 4B 00 02`; Temp F: `01 05 00 45 03 04 03 04 4C 00 02`.
- Off: `01 05 00 45 03 05 00 4C 00 02`.
- Stopwatch start: `01 05 00 45 06 03 04 51 00 02`.

**Disagreements on arg shape:**
- J/S always send `VIEW SUB` (+RGB): length 05 or 08. J `timebox.py:195-209`, S `:273-285`.
- H's `switch_view` sends only `VIEW` (length `04`): `04 00 45 VIEW` (H `__init__.py:45-48`). Evidently accepted by the device.
- H's colored clock/temp use a **4th color byte X** after RGB: head `09 00 45 00 <h24> R G B X` with X = `0xFF` (H `:97-102, 299-305`); J's doc says "RR GG BB" only (len 08) (J pm:54). Both are plausible; X may be a brightness/alpha-like byte **[inferred]**. Safest: send the 9-byte form like H.
- H's `set_temp_unit` (H `:113-117`) declares length `0x09` but sends no args - looks like a bug; do not copy.
- Colors in view commands are full 8-bit RGB (e.g. S passes 0-255 tuples, `timebox.py:25-26`), unlike images.

### 2.2 Set date/time `18`
Args (J pm:42-44): `YY_lo YY_hi MM DD hh mm ss [XX]` - year split as **low two digits first, then high two digits** (2026 -> `1A 14`; 26 then 20).
- J/S: 8 args (trailing `00`): `0B 00 18 ...` (J `timebox.py:117-129`, S `:195-207`). **[computed]** 2026-10-26 14:30:05 ->
  `01 0B 00 18 1A 14 0A 1A 0E 1E 05 00 A6 00 02`.
- H: 7 args, no trailing byte: `0A 00 18 ...` (H `__init__.py:316-323`). **[computed]** same moment ->
  `01 0A 00 18 1A 14 0A 1A 0E 1E 05 A5 00 02`.
- Both work in the field; S/J call set_time before showing clock (S `:350-352`, J daemon `:139`). The clock view shows device time, so set it first.
- D (Aurabox) hard-codes year/month/day and only varies h/m/s: `0B 00 18 11 14 0B 1C h m s 05` (D `divoom_protocol.py:84-87`) - confirms 8-arg form.

## 3. Static image `44` (11x11)

Payload (J `messages.py:64-80`, `protocol.md:45-48`; H `__init__.py:218-223`):
```
BD 00  44  00 0A 0A 04  <182 bytes pixel data>
```
- `BD 00` = length 189. `00 0A 0A 04` is a fixed sub-header (0x0A,0x0A = 10,10 is Aurabox heritage; Mini still uses it - D `divoom_protocol.py:10`, E:364).
- Then checksum + escaping as in 1.3. Total on wire = 1 + 189 + 2 + 1 plus escapes (~193-400+ bytes).

### Color / pixel packing
- **12-bit color: 4 bits per channel** (0..15). Convert 8-bit by taking the top nibble: `v >> 4`. J `divoom_image.py:11-14, 156`; H `__init__.py:196-201` (`& 0xf0`). J's gamma table exists but build_img does not call it (`timeboximage.py:19-30` vs `divoom_image.py:156`).
- Pixel order: row by row, left to right, top to bottom (y outer, x inner). J `messages.py:72-74`; `protocol.md:46`; H `:191-193` (`product(range(sz), range(sz))` with `y, x = c`).
- Within a pixel the nibble order is **R, G, B**. The nibble stream is packed **low nibble first** within each byte:
  nibble index `n` goes to byte `n>>1`, shifted `<<4` if `n` is odd. J `messages.py:70-79`; protocol.md:47 ("first color occupies the lowest four bits").
- 121 pixels x 3 = 363 nibbles -> 182 bytes (last byte's high nibble is 0 padding) (J pm:48).
- Alpha: H treats alpha <= 32 as black (`__init__.py:196-201`).

Worked example **[computed]**: pixel0 = red (F,0,0), pixel1 = green (0,F,0), pixel2 = blue (0,0,F), rest black:
nibbles `F 0 0 | 0 F 0 | 0 0 F | 0...` -> bytes `0F 00 0F 00 0F 00 00 ...` (182 total). Message:
`01 BD 00 44 00 0A 0A 04 0F 00 0F 00 0F 00 00 ... 00 <cs_lo> <cs_hi> 02` - the computed tail of that exact image is `... 00 00 00 46 03 04 02`
(checksum 0x0146? lo=0x46, hi=0x01 escaped to `03 04`).

**Escaping hazard:** pixel bytes of value `01`, `02`, `03` are legal image data (e.g. very dark pixels) and must be escaped as above (J `messages.py:53-62` escapes the entire payload including image data; H `conv_image` masks data `:222`).
So the wire length of an image is variable.

### Sending notes
- No view switch is needed before an image in J/S (they just send `44`). The device shows the image immediately.
- Sending a new `44` replaces the current one - this is how J scrolls text (a stream of static images, `timebox.py:51-62`).

## 4. Animation frames `49`

Per-frame message (J `messages.py:82-98`; H `__init__.py:226-239`):
```
BF 00  49  00 0A 0A 04  FRAME_INDEX  DELAY  <182 bytes pixel data>
```
- Length `BF 00` = 191 (7 header + 2 + 182). Pixel packing identical to 3 (J builds nibble index starting at 18 = byte 9).
- `FRAME_INDEX` starts at 0 and increments (J `timebox.py:187-193`; H `:230-236`). There is **no frame count field and no end marker**: the device loops over the frames it received. D says the animation "will run unlimited" (D `divoom_protocol.py:53`).
- `DELAY`: one byte shared by all frames; J default 1 (`timebox.py:187`); D default `0x05` and "smaller number means faster" (D readme:65). H derives `delay = int(gif_frame_ms/200)`, min 1 (H `__init__.py:273-275`) so one unit ≈ 200 ms **[inferred]**; H README says min 200 ms and no per-frame delays (README lines 161-162).
- Note escape of frame index/delay bytes if they are 01..03 (D readme:64). **[computed]** frame 0, delay 1 header: `01 BF 00 49 00 0A 0A 04 00 03 04 ...`.
- Frames are sent as separate messages back-to-back; H reads a reply only after the last frame (H `:279-284`).
- Maximum frames: not stated in any repo for the Mini.

## 5. Other devices / differences

### 5.1 Aurabox (D) - same framing, different payload
- 10x10 display, **one nibble per pixel**, 3-bit palette 0..7 black, red, green, yellow, blue, pink, light blue, white; lower nibble = left pixel; image `0x44`, length `0x39` (57 = 7 + 50 bytes); animation `0x3B` = 59 (D `divoom_protocol.py:10-11`, readme:23-64, `divoom_image.py:24-32`).
- Brightness uses opcode **`0x32`** with raw fixed packets `01 04 00 32 3F 75 00 02` (dark), `01 04 00 32 D2 08 03 04 02` (bright), `01 04 00 32 00 36 00 02` (off) (D `divoom_protocol.py:72-82`). The Mini (per H) uses `0x74` instead; `0x32` on the Mini is **untested**.
- D "show time" `01 04 00 45 00 49 00 02` and temp `01 04 00 45 03 04 4A 00 02` (view 0 / view 1) (D `:64-70`) agree with the Mini's `45` command.
- D confirms start 0x01, end 0x02, escape prefix 0x03, checksum LE of unescaped bytes.

### 5.2 Timebox **Evo** (E) - what differs from the Mini
- Length/checksum/start/end/endianness identical (E:66-87), but **E documents no byte escaping**. Do not assume the Evo escapes; the Mini does.
- Messages are split into chunks of **1332 hex chars (666 bytes)** per Bluetooth write (E:90).
- Display is 16x16. Images/animations are **palette based**, not 12-bit raw: `44 00 0A 0A 04 AA LLLL 000000 NN COLORS PIXELS` where PIXELS are bit-packed indices of `ceil(log2(ncolors))` bits each, LSB-first (E:243-373). Animation = `49 LLLL NN FRAMES` split into 400-hex-char packets, frame header `AA LLLL TTTT RR NN` with delay in **ms** (E:322-358).
- `45` is "switch channel" with different numbering: 00 time, 01 lightning, 02 cloud, 03 VJ effects, 04 visualization, 05 animation, 06 scoreboard (E:150-159). Mini's view 02 = off, 06 = stopwatch, 07 = scoreboard differ.
- Evo time channel: `45 00 01 TT XX WW EE CC RRGGBB` (clock style + show flags + color) (E:167-182).
- Evo scoreboard: `45 06 00 RRRR BBBB` (scores 0-999, LE) (E:228-239). Mini score payload unknown.
- Evo temperature/weather: `5F TT WW` (E:96-118); brightness `74 BB` 0-100 (E:120-133) - `74` same opcode as Mini.
- Evo request settings `46` (E:139-142). Replies are `04 CC 55 ...` same as Mini (E:379-392).
- Evo lightning `45 01 RRGGBB BB TT PP 000000` (E:184-199); VJ `45 03 TT`; visualizer `45 04 TT` (E:206-220).

## 6. Gotchas / operational notes

1. **Pair first** (OS-level). H hits `[Errno 16] Resource busy` or `[Errno 112] Host is down` when the adapter/pairing is stale; fix = reset the dongle and re-pair (H README:113-143). Likely the Mini accepts one RFCOMM client at a time **[inferred]**.
2. **Read/discard the HELLO** (`00 05 48 45 4C 4C 4F 00`) after connect or the first `recv` will return it instead of an ACK (S `:50-52`; H defines it `:15-16` but its connect never reads it - dead code `timebox.py:20-24`).
3. J/S set the socket non-blocking after connect (J `timebox.py:94`, S `:171`) and use `select` with 0.1 s (J `:101-105`). J daemon retries connecting up to 10 times, sleeping 10 s (J daemon `:131-138`).
4. H blocks on `recv(256)` after every command; it calls `.decode()` on raw bytes, which can raise on bytes >= 0x80 (H `timebox.py:35`) - treat replies as bytes.
5. Not seen anywhere: a documented required delay between writes for the Mini. Text scrolling in J sleeps `1/speed` s between images (default speed 20, `timebox.py:51-62`); animation min 200 ms.
6. Max packet: biggest Mini packet is the animation frame, 1+191+2+1 = 195 bytes unescaped (up to ~390 if all data bytes are 01-03). E's 666-byte chunking is Evo-specific.
7. The firmware tolerates `45` with 1 arg (H) or 2+ args (J/S). Prefer the longer form when selecting clock/temp so 12/24h and C/F are explicit.
8. Colors in images are 4-bit/channel - expect banding; no gamma is applied in J.
9. Volume `08` max 0x10 (J pm:36). Sound itself is A2DP, not RFCOMM.
10. Our implementation checklist: build payload -> sum -> append LE checksum -> escape whole thing (payload+checksum) -> wrap 01..02; on receive, skip until 0x01, read to 0x02, unescape, verify checksum.

## 7. Quick opcode summary
`05` radio on/off, `08` volume set (0-16), `09` volume get, `0A` mute set, `0B` mute get, `18` set date/time, `44` static image,
`45` switch view (00 clock, 01 temp, 02 off, 03 anim, 04 graph, 05 image, 06 stopwatch, 07 scoreboard), `49` animation frame,
`59` temperature (device push), `60` radio freq get, `61` radio freq set, `74` brightness. (Evo only: `46`, `5F`.)

## 8. Verified on a real Timebox Mini (2026-10-26)
| CMD | Args | Reply payload (after `CMD 55`) | Notes |
|---|---|---|---|
| `42` get alarms | – | 3 × 10-byte records | record = idx, on, hour, min, weekday mask (bit0 Mon … bit6 Sun), mode, trigger, fm hi, fm lo, volume |
| `43` set alarm | one 10-byte record | – (ack) | mode `0A` = ring (volume byte 0 = **silent**, verified); mode `00` is NOT silent: it plays Bluetooth music (the box sends PLAY → Music opens on the Mac) and beeps when none arrives; trigger `01` = flash clock, `04` = the box's built-in alarm animation (NOT the uploaded 0x49 one; checked 2026-10-27); keep fm `00 00`. Rings with the Mac off. stop it with `A5 00 00 00` |
| `A5` alarm listen | `00 00 00` | – (no ack) | per Divoom's official docs this is the alarm-sound *preview* (`on mode vol`), not a stop; so alone it is unreliable. A5 + re-saving the ringing alarm (off, then on via `43`) stops it (verified 2026-10-27). The box's own button always works. While ringing, the box ignores images and drowns our audio |
| `46` get settings | – | 23 bytes | byte 8 = brightness; the rest is still undecoded |
| `09` get volume | – | 1 byte | the box's OWN volume (beeps/alarms), not the Bluetooth audio level |
| `45` view | `04 00` visualizer, `06 01` stopwatch, `01 01` temp °F | – | ack'd |
| `2B FF`, `2D FF`, `97 00` | | no reply | harmless, just unknown to the Mini |
| **`61` set FM frequency** | | **box freezes → pinhole reset** | never send |

| `82` alarm voice memo | `00/01/02 00` | no reply | ignored by the Mini: no on-box recording |
| `13` work mode | – | `00` (Bluetooth) | read-only |
| `59` device temperature | – | `00 01 00` | the Mini has no temp sensor (temp screen shows 0) |

## Tested against Divoom's official Bluetooth docs (2026-10-28, Timebox Mini)

| Cmd | Result on the Mini |
|---|---|
| `72 01 01 R16 B16` scoreboard | ✅ works, but only while the score screen (`45 07`) is showing. Sent alone it is acked and nothing shows. `tb score` does both |
| `71 01` / `71 00` read scoreboard / stopwatch | ✅ replies `01 on R16 B16` / `00 running` |
| `72 00 1/0/2` stopwatch start/pause/reset | acked, nothing visible outside the stopwatch screen |
| `71 03` / `72 03` countdown | ❌ no reply (not on the Mini) |
| `53` read memorials / `54` set memorial | ✅ work. A memorial plays a pumpkin animation **with music and no volume field**, so it can't be silent; not used |
| `51` alarm GIF (frame body after `43` trigger 04) | ❌ ignored: the box still plays its built-in alarm animation. Box kept working |

