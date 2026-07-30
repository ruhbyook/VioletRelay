# Violet Relay branding

The Violet Relay mark is an original project asset: a white play symbol relayed
between violet and cyan endpoints on a midnight tile. It deliberately avoids
letters, platform trademarks, and fine details so it remains recognizable at
Windows taskbar and file-icon sizes.

The 1024 px transparent master was created with OpenAI's built-in image
generation, then chroma-keyed and edge-cleaned. `scripts/generate_icons.py`
deterministically normalizes that master and writes the QML/GitHub PNGs,
multi-resolution Windows ICO, and 1280 × 640 social preview. The exact source
prompt is recorded in [IMAGEGEN_PROMPT.md](IMAGEGEN_PROMPT.md).

All committed branding assets are distributed under the same
GPL-3.0-or-later terms as Violet Relay.
