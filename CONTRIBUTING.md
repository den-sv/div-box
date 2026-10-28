# Contributing

Thanks for stopping by! Testers, tinkerers and first-time contributors are all welcome. This is a free hobby
project, so there's no pressure and no stupid questions.

## Testing a box

1. Pair it like a Bluetooth speaker, then run `tb ui` (macOS) or `python3 tb.py ui` (Linux/Windows).
2. Try the things in the README's **Testers wanted** list.
3. Open a [device report](.github/ISSUE_TEMPLATE/device-report.md) issue. Include your model, OS, and what
   worked or didn't. `tb status` and the log in the dashboard's **Timebox info** card help.

Remove anything personal before you paste (your box's full Bluetooth address, your city if you like).

## Changing code

- **Standard library only.** No `pip install`. Optional outside tools (ffmpeg, espeak-ng) must stay optional.
- **Never guess opcodes on a real box.** Blind probing has frozen a Mini more than once (pinhole reset). New
  commands come from captured traffic (Android *Bluetooth HCI snoop log*) or documented projects; see
  [docs/PROTOCOL.md](docs/PROTOCOL.md).
- Keep the Mini's bytes identical when touching `timebox/proto.py`. Other models go through
  `proto.model()["family"]` ([docs/MODELS.md](docs/MODELS.md)).
- Match the style around you: small functions, few comments, comments say *why*.
- UI changes: check a laptop width and a phone width (~390 px). Update `docs/img/` screenshots
  (`python3 tools/previews.py` regenerates the LED previews).

## Where things live

| File | What |
|---|---|
| `timebox/proto.py` | message framing and every command, per model |
| `timebox/models.py` | box models, auto-detect from the Bluetooth name |
| `timebox/device.py` | the Bluetooth link (macOS bridge app, or a socket elsewhere) |
| `timebox/gfx.py`, `effects.py`, `data.py` | 11×11 drawing, font, icons, animations, weather/stocks frames |
| `timebox/app.py` | the background service: scheduler, alarms, rotation |
| `timebox/web.py`, `ui.html` | the dashboard (local only, token-protected) |
| `timebox/cli.py` | the `tb` command |
| `bridge/` | ~150-line Swift helper for macOS Bluetooth |

Pull requests: small and focused is best. Say what you tested it on.

## Keep it clean (legal)

- Write your own code. Don't paste code from projects without a license or under GPL, and never add Divoom's
  app code, firmware, logos, product photos, app screenshots or icons.
- Don't link to decompiled Divoom apps or firmware dumps.
- Learn new commands by watching your own box's Bluetooth traffic or from openly licensed docs, and say where
  it came from in the PR.
