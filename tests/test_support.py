from pathlib import Path

from PIL import Image

from xmediaplayerx.support import (
    BITCOIN_ADDRESS,
    BITCOIN_URI,
    ETHEREUM_ADDRESS,
    ETHEREUM_NETWORK,
    USDC_NETWORK,
)


ROOT = Path(__file__).resolve().parents[1]
ASSETS = ROOT / "src" / "xmediaplayerx" / "qml" / "assets"


def test_public_support_addresses_and_networks_are_unambiguous():
    assert BITCOIN_ADDRESS == "bc1q4udt9zp44v23c3geph6tq5h5a659xa0qqph2es"
    assert BITCOIN_URI == f"bitcoin:{BITCOIN_ADDRESS}"
    assert ETHEREUM_ADDRESS == "0xAd53452fB8ae492a96154D12aa671D3331AA6680"
    assert ETHEREUM_NETWORK == "Ethereum Mainnet"
    assert USDC_NETWORK == "Ethereum Mainnet (ERC-20)"


def test_support_qr_assets_are_committed_square_images():
    for name in ("support-bitcoin.png", "support-ethereum.png"):
        path = ASSETS / name
        assert path.is_file()
        with Image.open(path) as image:
            assert image.format == "PNG"
            assert image.size == (512, 512)
            assert image.mode == "RGB"
