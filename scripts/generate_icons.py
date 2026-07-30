"""Generate ReelFerry's committed master, QML PNG, and Windows ICO."""

from pathlib import Path

from PIL import Image, ImageDraw, ImageFilter, ImageFont


ROOT = Path(__file__).resolve().parents[1]
MASTER_ICON = ROOT / "assets" / "branding" / "reelferry-icon-master.png"
GITHUB_ICON = ROOT / "assets" / "branding" / "reelferry-logo.png"
SOCIAL_PREVIEW = ROOT / "assets" / "branding" / "reelferry-social-preview.png"
QML_ICON = (
    ROOT
    / "src"
    / "reelferry"
    / "qml"
    / "assets"
    / "reelferry-icon.png"
)
WINDOWS_ICON = ROOT / "assets" / "reelferry.ico"
WORK_SIZE = 2048


def _horizontal_gradient(
    start: tuple[int, int, int, int],
    end: tuple[int, int, int, int],
    *,
    start_x: int = 0,
    end_x: int = WORK_SIZE - 1,
) -> Image.Image:
    image = Image.new("RGBA", (WORK_SIZE, WORK_SIZE))
    draw = ImageDraw.Draw(image)
    for x in range(WORK_SIZE):
        ratio = max(0.0, min(1.0, (x - start_x) / (end_x - start_x)))
        color = tuple(
            round(first + ((last - first) * ratio))
            for first, last in zip(start, end)
        )
        draw.line((x, 0, x, WORK_SIZE), fill=color)
    return image


def _build_master() -> Image.Image:
    canvas = Image.new("RGBA", (WORK_SIZE, WORK_SIZE), (0, 0, 0, 0))
    tile_mask = Image.new("L", canvas.size)
    ImageDraw.Draw(tile_mask).rounded_rectangle(
        (154, 154, 1894, 1894),
        radius=410,
        fill=255,
    )

    background = _horizontal_gradient(
        (7, 10, 19, 255),
        (17, 24, 42, 255),
    )
    canvas.alpha_composite(
        Image.composite(background, Image.new("RGBA", canvas.size), tile_mask)
    )
    border = ImageDraw.Draw(canvas)
    border.rounded_rectangle(
        (160, 160, 1888, 1888),
        radius=404,
        outline=(56, 68, 98, 205),
        width=10,
    )

    # A filled geometric R remains recognizable after Windows downsamples it to
    # taskbar and file-icon sizes. The previous stroked construction developed
    # a boxy, broken-looking bowl at 16-32 px.
    mark_mask = Image.new("L", canvas.size)
    mark = ImageDraw.Draw(mark_mask)
    mark.rounded_rectangle(
        (500, 398, 784, 1650),
        radius=142,
        fill=255,
    )
    mark.rounded_rectangle(
        (610, 398, 1546, 1122),
        radius=348,
        fill=255,
    )
    mark.rectangle(
        (642, 398, 1000, 680),
        fill=255,
    )
    mark.line(
        (895, 1016, 1504, 1570),
        fill=255,
        width=272,
    )
    mark.ellipse((759, 880, 1031, 1152), fill=255)
    mark.ellipse((1368, 1434, 1640, 1706), fill=255)

    # Open a generous counter inside the bowl. Rounded geometry avoids the
    # black rectangular notch that made the old mark look damaged.
    counter_mask = Image.new("L", canvas.size)
    counter = ImageDraw.Draw(counter_mask)
    counter.rounded_rectangle(
        (784, 622, 1296, 900),
        radius=139,
        fill=255,
    )
    mark_mask.paste(0, mask=counter_mask)

    # Keep the glow restrained so the silhouette stays crisp at small sizes.
    glow_alpha = mark_mask.filter(ImageFilter.GaussianBlur(42)).point(
        lambda value: round(value * 0.42)
    )
    glow = Image.new("RGBA", canvas.size, (124, 92, 255, 0))
    glow.putalpha(glow_alpha)
    canvas.alpha_composite(glow)
    ribbon = _horizontal_gradient(
        (129, 92, 255, 255),
        (47, 211, 255, 255),
        start_x=470,
        end_x=1580,
    )
    canvas.alpha_composite(
        Image.composite(ribbon, Image.new("RGBA", canvas.size), mark_mask)
    )

    # The play glyph sits in the R's counter instead of cutting into the
    # letterform. It is intentionally small enough that the R reads first.
    play_shadow = Image.new("RGBA", canvas.size)
    shadow_draw = ImageDraw.Draw(play_shadow)
    shadow_draw.polygon(
        ((968, 673), (968, 849), (1126, 761)),
        fill=(0, 0, 0, 155),
    )
    play_shadow = play_shadow.filter(ImageFilter.GaussianBlur(14))
    canvas.alpha_composite(play_shadow)
    ImageDraw.Draw(canvas).polygon(
        ((952, 657), (952, 833), (1110, 745)),
        fill=(255, 255, 255, 255),
    )

    return canvas.resize((1024, 1024), Image.Resampling.LANCZOS)


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
    ambient_draw.ellipse(
        (-190, -250, 690, 720),
        fill=(124, 92, 255, 54),
    )
    ambient_draw.ellipse(
        (840, -330, 1500, 480),
        fill=(49, 208, 255, 32),
    )
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
    draw.text((535, 211), "ReelFerry", font=title_font, fill=(249, 250, 255, 255))
    draw.rounded_rectangle(
        (540, 328, 760, 336),
        radius=4,
        fill=(124, 92, 255, 255),
    )
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
    image = _build_master()
    MASTER_ICON.parent.mkdir(parents=True, exist_ok=True)
    image.save(MASTER_ICON, optimize=True)

    qml_image = image.resize((512, 512), Image.Resampling.LANCZOS)
    qml_image.save(GITHUB_ICON, optimize=True)
    QML_ICON.parent.mkdir(parents=True, exist_ok=True)
    qml_image.save(QML_ICON, optimize=True)

    social_preview = _build_social_preview(image)
    social_preview.save(SOCIAL_PREVIEW, optimize=True)

    ico_image = image.resize((256, 256), Image.Resampling.LANCZOS)
    ico_image.save(
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
