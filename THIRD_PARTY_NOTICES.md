# Third-party notices

Violet Relay is distributed under GPL-3.0-or-later. It includes or depends on
third-party software whose copyright remains with its respective owners.

The portable release includes a `licenses` directory containing license files
collected from the exact Python environment used for that build. The following
components are particularly important:

- **Qt for Python / PySide6 / Shiboken6** — LGPL-3.0-only, GPL-2.0-only, or
  GPL-3.0-only. Violet Relay uses the GPL-3.0 option. Source and license
  information: <https://code.qt.io/cgit/pyside/pyside-setup.git/>.
- **FFmpeg 8.1.2 essentials build** — GPL version 3 because the build enables
  GPL components, including libx264 and libx265. Public Violet Relay packages
  do not redistribute it; the optional verified archive is downloaded directly
  from its provider only after user consent. Developer/private bundled builds
  include `licenses/FFmpeg/LICENSE.txt`. See `FFMPEG_SOURCE.md`.
- **pyatv 0.18.0** — MIT License. <https://github.com/postlund/pyatv>
- **python-zeroconf** — LGPL-2.1-or-later.
- **aiohttp** — Apache-2.0 AND MIT.
- **cryptography** — Apache-2.0 OR BSD-3-Clause.
- **qrcode** — BSD-3-Clause. It is a development-only generator for the
  committed offline support QR images and is not imported by the application.
- **Python** — Python Software Foundation License.

The dependency report generated for each release is informational; the license
texts shipped beside it control. No Apple software is bundled. AirPlay and Apple
TV are trademarks of Apple Inc. Violet Relay is an unofficial project and is not
affiliated with, endorsed by, or certified by Apple Inc.
