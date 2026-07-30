"""Generate ReelFerry's committed master, QML PNG, and Windows ICO."""

from pathlib import Path

from PIL import Image, ImageDraw, ImageFilter


ROOT = Path(__file__).resolve().parents[1]
MASTER_ICON = ROOT / "assets" / "branding" / "reelferry-icon-master.png"
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
        (170, 170, 1878, 1878),
        radius=390,
        fill=255,
    )

    background = _horizontal_gradient(
        (8, 11, 20, 255),
        (18, 25, 43, 255),
    )
    canvas.alpha_composite(
        Image.composite(background, Image.new("RGBA", canvas.size), tile_mask)
    )
    border = ImageDraw.Draw(canvas)
    border.rounded_rectangle(
        (174, 174, 1874, 1874),
        radius=386,
        outline=(55, 67, 96, 210),
        width=12,
    )

    mark_mask = Image.new("L", canvas.size)
    mark = ImageDraw.Draw(mark_mask)
    width = 188
    mark.line((585, 500, 585, 1570), fill=255, width=width)
    mark.ellipse((491, 406, 679, 594), fill=255)
    mark.ellipse((491, 1476, 679, 1664), fill=255)
    mark.line((585, 500, 1115, 500), fill=255, width=width)
    mark.arc(
        (770, 500, 1510, 1120),
        start=-90,
        end=90,
        fill=255,
        width=width,
    )
    mark.line((1140, 1120, 585, 1120), fill=255, width=width)
    mark.line((865, 1110, 1460, 1580), fill=255, width=width)
    mark.ellipse((771, 1016, 959, 1204), fill=255)
    mark.ellipse((1366, 1486, 1554, 1674), fill=255)

    glow = Image.new("RGBA", canvas.size, (124, 92, 255, 0))
    glow.putalpha(mark_mask.filter(ImageFilter.GaussianBlur(70)))
    canvas.alpha_composite(glow)
    ribbon = _horizontal_gradient(
        (124, 92, 255, 255),
        (49, 208, 255, 255),
        start_x=470,
        end_x=1560,
    )
    canvas.alpha_composite(
        Image.composite(ribbon, Image.new("RGBA", canvas.size), mark_mask)
    )

    play_shadow = Image.new("RGBA", canvas.size)
    shadow_draw = ImageDraw.Draw(play_shadow)
    shadow_draw.polygon(
        ((905, 679), (905, 959), (1155, 819)),
        fill=(0, 0, 0, 185),
    )
    play_shadow = play_shadow.filter(ImageFilter.GaussianBlur(22))
    canvas.alpha_composite(play_shadow)
    ImageDraw.Draw(canvas).polygon(
        ((885, 659), (885, 939), (1135, 799)),
        fill=(255, 255, 255, 255),
    )

    return canvas.resize((1024, 1024), Image.Resampling.LANCZOS)


def main() -> None:
    image = _build_master()
    MASTER_ICON.parent.mkdir(parents=True, exist_ok=True)
    image.save(MASTER_ICON, optimize=True)

    qml_image = image.resize((512, 512), Image.Resampling.LANCZOS)
    QML_ICON.parent.mkdir(parents=True, exist_ok=True)
    qml_image.save(QML_ICON, optimize=True)

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
    print(f"Wrote {QML_ICON.relative_to(ROOT)}")
    print(f"Wrote {WINDOWS_ICON.relative_to(ROOT)}")


if __name__ == "__main__":
    main()
