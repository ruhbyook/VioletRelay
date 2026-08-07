import tomllib
from pathlib import Path

from PIL import Image

from violetrelay import __version__


ROOT = Path(__file__).resolve().parents[1]


def test_package_metadata_and_runtime_version_match_violetrelay_brand():
    with (ROOT / "pyproject.toml").open("rb") as stream:
        project = tomllib.load(stream)["project"]

    assert project["name"] == "violetrelay"
    assert project["version"] == __version__ == "0.7.1"
    assert project["scripts"] == {"violetrelay": "violetrelay.app:main"}
    version_info = (
        ROOT / "assets" / "violetrelay-version-info.txt"
    ).read_text(encoding="utf-8")
    assert "StringStruct('ProductName', 'Violet Relay')" in version_info
    assert "StringStruct('ProductVersion', '0.7.1.0')" in version_info


def test_runtime_qml_uses_only_the_current_visible_brand():
    qml = (ROOT / "src" / "violetrelay" / "qml" / "Main.qml").read_text(
        encoding="utf-8"
    )

    assert "Violet Relay" in qml
    assert "Play here. Watch there." in qml
    assert "Select them with CC before you press Cast" in qml
    assert "ReelFerry" not in qml
    assert "xMediaPlayerx" not in qml
    assert "violetrelay-icon.png" in qml


def test_public_copy_presents_airplay_as_optional_and_uses_current_brand():
    public_files = (
        ROOT / "README.md",
        ROOT / "PRIVACY.md",
        ROOT / "docs" / "releases" / "0.7.1.md",
    )
    public_copy = "\n".join(
        path.read_text(encoding="utf-8") for path in public_files
    )

    assert "AirPlay casting is an optional extra" in public_copy
    assert "Only if you want AirPlay casting" in public_copy
    assert "Free Windows Media Player with AirPlay Casting" in public_copy
    assert "compatible smart TV" in public_copy
    assert "free and open-source Windows 11 media player" in public_copy
    assert "ReelFerry" not in public_copy
    assert "xMediaPlayerx" not in public_copy


def test_search_focused_guides_cover_primary_use_cases():
    guides = {
        "cast-mkv-windows-to-apple-tv.md": "Cast MKV from Windows 11 to Apple TV",
        "cast-subtitles-windows-to-apple-tv.md": (
            "Cast Video with Subtitles from Windows to Apple TV"
        ),
        "airplay-video-windows-11.md": "AirPlay Video from Windows 11 to Apple TV",
    }

    for filename, heading in guides.items():
        copy = (ROOT / "docs" / "guides" / filename).read_text(encoding="utf-8")
        assert f"# How to {heading}" in copy
        assert "Violet Relay" in copy
        assert "releases/latest" in copy


def test_icon_buttons_use_normalized_vector_geometry():
    qml = (ROOT / "src" / "violetrelay" / "qml" / "Main.qml").read_text(
        encoding="utf-8"
    )
    vector_icon = (
        ROOT / "src" / "violetrelay" / "qml" / "VectorIcon.qml"
    ).read_text(encoding="utf-8")

    assert qml.count("padding: 0") >= 3
    for icon_name in (
        "plus",
        "link",
        "cast",
        "captions",
        "grid",
        "heart",
        "info",
        "previous",
        "play",
        "pause",
        "next",
        "volume",
        "muted",
        "fullscreen",
        "exit-fullscreen",
    ):
        assert f'case "{icon_name}":' in vector_icon
    assert "context.scale(width / 20, height / 20)" in vector_icon
    assert "Segoe Fluent Icons" not in qml


def test_violetrelay_icon_assets_are_valid_and_multiresolution():
    with Image.open(
        ROOT / "assets" / "branding" / "violetrelay-icon-master.png"
    ) as master:
        assert master.mode == "RGBA"
        assert master.size == (1024, 1024)
    with Image.open(
        ROOT / "assets" / "branding" / "violetrelay-logo.png"
    ) as github:
        assert github.mode == "RGBA"
        assert github.size == (512, 512)
    with Image.open(
        ROOT / "assets" / "branding" / "violetrelay-social-preview.png"
    ) as social:
        assert social.mode == "RGB"
        assert social.size == (1280, 640)
    with Image.open(
        ROOT
        / "src"
        / "violetrelay"
        / "qml"
        / "assets"
        / "violetrelay-icon.png"
    ) as qml:
        assert qml.size == (512, 512)
    with Image.open(ROOT / "assets" / "violetrelay.ico") as windows:
        assert windows.format == "ICO"
        assert (256, 256) in windows.info["sizes"]
