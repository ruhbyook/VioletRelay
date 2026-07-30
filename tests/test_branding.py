import tomllib
from pathlib import Path

from PIL import Image

from violetrelay import __version__


ROOT = Path(__file__).resolve().parents[1]


def test_package_metadata_and_runtime_version_match_violetrelay_brand():
    with (ROOT / "pyproject.toml").open("rb") as stream:
        project = tomllib.load(stream)["project"]

    assert project["name"] == "violetrelay"
    assert project["version"] == __version__ == "0.6.0"
    assert project["scripts"] == {"violetrelay": "violetrelay.app:main"}
    version_info = (
        ROOT / "assets" / "violetrelay-version-info.txt"
    ).read_text(encoding="utf-8")
    assert "StringStruct('ProductName', 'Violet Relay')" in version_info
    assert "StringStruct('ProductVersion', '0.6.0.0')" in version_info


def test_runtime_qml_uses_only_the_current_visible_brand():
    qml = (ROOT / "src" / "violetrelay" / "qml" / "Main.qml").read_text(
        encoding="utf-8"
    )

    assert "Violet Relay" in qml
    assert "Play here. Watch there." in qml
    assert "Previously ReelFerry" in qml
    assert "xMediaPlayerx" not in qml
    assert "violetrelay-icon.png" in qml


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
