# Notices

## Trademarks

Divoom, Timebox, Timebox Mini, Timebox Evo, Aurabox, Pixoo, Ditoo, Tivoo and related names are trademarks of
Divoom. This is an independent, unofficial hobby project. It is not made, approved, sponsored or supported by
Divoom. Product names are used only to say which devices this tool can talk to. No Divoom logos, product photos,
app screenshots, icons, graphics, software or firmware are included; all pixel art and previews in this repo were
drawn by this project.

## How it was made (interoperability)

This tool talks to a device you own over Bluetooth, so it works on your own computer without the official app.
It was written from scratch from public community documentation and observing our own device, for the sole
purpose of interoperability. It does not contain, modify, patch or redistribute any Divoom app, firmware or
cloud service, and it never contacts Divoom servers. Divoom itself publishes developer documentation for its
devices at <https://docin.divoom-gz.com/web/#/5/374>; this project links to it but does not copy it.

## Third-party data

- Weather: [Open-Meteo.com](https://open-meteo.com/), data licensed under
  [CC BY 4.0](https://creativecommons.org/licenses/by/4.0/). Free for non-commercial use.
- Stock quotes: fetched by your own computer from public quote pages (Yahoo Finance, Stooq). These are not
  official APIs, may be delayed or stop working, and are for your personal, non-commercial use under those
  providers' terms. Nothing is stored or redistributed.

## Prior work

The protocol knowledge comes from earlier open-source projects (see "Thanks" in the README). Parts of the
multi-model support follow the per-device logic of these MIT-licensed projects, whose notices are kept here:

- [hass-divoom](https://github.com/d03n3rfr1tz3/hass-divoom): Copyright (c) 2020 Dirk Sarodnick, MIT License
- [node-divoom-timebox-evo](https://github.com/RomRider/node-divoom-timebox-evo): Copyright (c) 2019 Jérôme Wiedemann, MIT License

> Permission is hereby granted, free of charge, to any person obtaining a copy of this software and associated
> documentation files (the "Software"), to deal in the Software without restriction, including without limitation
> the rights to use, copy, modify, merge, publish, distribute, sublicense, and/or sell copies of the Software, and
> to permit persons to whom the Software is furnished to do so, subject to the following conditions: The above
> copyright notice and this permission notice shall be included in all copies or substantial portions of the
> Software. THE SOFTWARE IS PROVIDED "AS IS", WITHOUT WARRANTY OF ANY KIND.

No code from unlicensed or GPL projects was copied.

## No warranty

Use at your own risk. Sending commands to a device can freeze it until it is reset, and may affect your warranty.
See the MIT [LICENSE](LICENSE): the software is provided "as is", without warranty of any kind.
