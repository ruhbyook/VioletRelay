"""Package Violet Relay's source artwork into app and repository assets."""

from pathlib import Path

from PIL import Image, ImageDraw, ImageFilter, ImageFont


ROOT = Path(__file__).resolve().parents[1]
MASTER_ICON = ROOT / "assets" / "branding" / "violetrelay-icon-master.png"
GITHUB_ICON = ROOT / "assets" / "branding" / "violetrelay-logo.png"
SOCIAL_PREVIEW = ROOT / "assets" / "branding" / "violetrelay-social-preview.png"
QML_ICON = (
    ROOT
    / "src"
    / "violetrelay"
    / "qml"
    / "assets"
    / "violetrelay-icon.png"
)
WINDOWS_ICON = ROOT / "assets" / "violetrelay.ico"


def _load_master() -> Image.Image:
    """Normalize the generated source art to a centered 1024 px icon canvas."""
    source = Image.open(MASTER_ICON).convert("RGBA")
    alpha_box = source.getchannel("A").getbbox()
    if alpha_box is None:
        raise RuntimeError(f"{MASTER_ICON} contains no visible artwork")
    artwork = source.crop(alpha_box)
    artwork.thumbnail((900, 900), Image.Resampling.LANCZOS)
    canvas = Image.new("RGBA", (1024, 1024), (0, 0, 0, 0))
    canvas.alpha_composite(
        artwork,
        ((canvas.width - artwork.width) // 2, (canvas.height - artwork.height) // 2),
    )
    return canvas


def _brand_font(size: int, *, bold: bool = False) -> ImageFont.FreeTypeFont:
    candidates = [
        Path("C:/Windows/Fonts") / ("segoeuib.ttf" if bold else "segoeui.ttf"),
        Path("/usr/share/fonts/truetype/dejavu")
        / ("DejaVuSans-Bold.ttf" if bold else "DejaVuSans.ttf"),
    ]
    for candidate in candidates:
        if candidate.is_file():
            return ImageFont.truetype(str(candidate), size=size)
    return ImageFont.load_default(size=size)


def _build_social_preview(icon: Image.Image) -> Image.Image:
    width, height = 1280, 640
    preview = Image.new("RGB", (width, height), (7, 10, 19))
    draw = ImageDraw.Draw(preview)
    for x in range(width):
        ratio = x / (width - 1)
        color = (
            round(7 + (10 * ratio)),
            round(10 + (14 * ratio)),
            round(19 + (23 * ratio)),
        )
        draw.line((x, 0, x, height), fill=color)

    ambient = Image.new("RGBA", (width, height), (0, 0, 0, 0))
    ambient_draw = ImageDraw.Draw(ambient)
    ambient_draw.ellipse((-190, -250, 690, 720), fill=(124, 92, 255, 54))
    ambient_draw.ellipse((840, -330, 1500, 480), fill=(49, 208, 255, 32))
    preview = Image.alpha_composite(
        preview.convert("RGBA"),
        ambient.filter(ImageFilter.GaussianBlur(100)),
    )

    display_icon = icon.resize((390, 390), Image.Resampling.LANCZOS)
    preview.alpha_composite(display_icon, (92, 125))

    draw = ImageDraw.Draw(preview)
    title_font = _brand_font(91, bold=True)
    tagline_font = _brand_font(36)
    detail_font = _brand_font(22)
    draw.text((535, 211), "Violet Relay", font=title_font, fill=(249, 250, 255, 255))
    draw.rounded_rectangle((540, 328, 760, 336), radius=4, fill=(124, 92, 255, 255))
    draw.text(
        (535, 363),
        "Play here. Watch there.",
        font=tagline_font,
        fill=(185, 197, 224, 255),
    )
    draw.text(
        (538, 425),
        "Windows media player · Apple TV casting",
        font=detail_font,
        fill=(120, 139, 177, 255),
    )
    return preview.convert("RGB")


def main() -> None:
    image = _load_master()
    MASTER_ICON.parent.mkdir(parents=True, exist_ok=True)
    image.save(MASTER_ICON, optimize=True)

    qml_image = image.resize((512, 512), Image.Resampling.LANCZOS)
    qml_image.save(GITHUB_ICON, optimize=True)
    QML_ICON.parent.mkdir(parents=True, exist_ok=True)
    qml_image.save(QML_ICON, optimize=True)

    _build_social_preview(image).save(SOCIAL_PREVIEW, optimize=True)

    image.resize((256, 256), Image.Resampling.LANCZOS).save(
        WINDOWS_ICON,
        format="ICO",
        sizes=[
            (16, 16),
            (24, 24),
            (32, 32),
            (48, 48),
            (64, 64),
            (128, 128),
            (256, 256),
        ],
    )
    print(f"Wrote {MASTER_ICON.relative_to(ROOT)}")
    print(f"Wrote {GITHUB_ICON.relative_to(ROOT)}")
    print(f"Wrote {SOCIAL_PREVIEW.relative_to(ROOT)}")
    print(f"Wrote {QML_ICON.relative_to(ROOT)}")
    print(f"Wrote {WINDOWS_ICON.relative_to(ROOT)}")


if __name__ == "__main__":
    main()
