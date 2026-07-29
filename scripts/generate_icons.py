"""Generate committed PNG/ICO application icons from the transparent master."""

from pathlib import Path

from PIL import Image


ROOT = Path(__file__).resolve().parents[1]
SOURCE = ROOT / "assets" / "branding" / "xmediaplayerx-icon-master.png"
QML_ICON = (
    ROOT
    / "src"
    / "xmediaplayerx"
    / "qml"
    / "assets"
    / "xmediaplayerx-icon.png"
)
WINDOWS_ICON = ROOT / "assets" / "xmediaplayerx.ico"


def main() -> None:
    image = Image.open(SOURCE).convert("RGBA")
    qml_image = image.copy()
    qml_image.thumbnail((512, 512), Image.Resampling.LANCZOS)
    QML_ICON.parent.mkdir(parents=True, exist_ok=True)
    qml_image.save(QML_ICON, optimize=True)

    ico_image = image.copy()
    ico_image.thumbnail((256, 256), Image.Resampling.LANCZOS)
    ico_image.save(
        WINDOWS_ICON,
        format="ICO",
        sizes=[(16, 16), (24, 24), (32, 32), (48, 48), (64, 64), (128, 128), (256, 256)],
    )
    print(f"Wrote {QML_ICON.relative_to(ROOT)}")
    print(f"Wrote {WINDOWS_ICON.relative_to(ROOT)}")


if __name__ == "__main__":
    main()
