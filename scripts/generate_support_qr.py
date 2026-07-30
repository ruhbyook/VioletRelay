"""Generate committed, offline QR assets for the public support addresses."""

import sys
from pathlib import Path

from PIL import Image
import qrcode
from qrcode.constants import ERROR_CORRECT_Q


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from xmediaplayerx.support import (  # noqa: E402
    BITCOIN_URI,
    ETHEREUM_ADDRESS,
)


OUTPUT_DIRECTORY = ROOT / "src" / "xmediaplayerx" / "qml" / "assets"
QR_SIZE = 512


def write_qr(data: str, destination: Path) -> None:
    qr = qrcode.QRCode(
        version=None,
        error_correction=ERROR_CORRECT_Q,
        box_size=12,
        border=4,
    )
    qr.add_data(data)
    qr.make(fit=True)
    generated = qr.make_image(fill_color="#080B12", back_color="white").convert(
        "RGB"
    )
    generated.thumbnail((448, 448), Image.Resampling.NEAREST)
    image = Image.new("RGB", (QR_SIZE, QR_SIZE), "white")
    image.paste(
        generated,
        ((QR_SIZE - generated.width) // 2, (QR_SIZE - generated.height) // 2),
    )
    destination.parent.mkdir(parents=True, exist_ok=True)
    image.save(destination, optimize=True)
    print(f"Wrote {destination.relative_to(ROOT)}")


def main() -> None:
    write_qr(BITCOIN_URI, OUTPUT_DIRECTORY / "support-bitcoin.png")
    # A plain EVM account address is safer here than an ETH payment URI: donors
    # must deliberately choose ETH or Ethereum-mainnet USDC in their wallet.
    write_qr(ETHEREUM_ADDRESS, OUTPUT_DIRECTORY / "support-ethereum.png")


if __name__ == "__main__":
    main()
