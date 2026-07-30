import tomllib
from pathlib import Path

from PIL import Image

from reelferry import __version__


ROOT = Path(__file__).resolve().parents[1]


def test_package_metadata_and_runtime_version_match_reelferry_brand():
    with (ROOT / "pyproject.toml").open("rb") as stream:
        project = tomllib.load(stream)["project"]

    assert project["name"] == "reelferry"
    assert project["version"] == __version__ == "0.5.0"
    assert project["scripts"] == {"reelferry": "reelferry.app:main"}
    version_info = (
        ROOT / "assets" / "reelferry-version-info.txt"
    ).read_text(encoding="utf-8")
    assert "StringStruct('ProductName', 'ReelFerry')" in version_info
    assert "StringStruct('ProductVersion', '0.5.0.0')" in version_info


def test_runtime_qml_uses_only_the_current_visible_brand():
    qml = (ROOT / "src" / "reelferry" / "qml" / "Main.qml").read_text(
        encoding="utf-8"
    )

    assert "ReelFerry" in qml
    assert "Play here. Watch there." in qml
    assert qml.count("xMediaPlayerx") == 1
    assert "Formerly xMediaPlayerx" in qml
    assert "reelferry-icon.png" in qml


def test_reelferry_icon_assets_are_valid_and_multiresolution():
    with Image.open(
        ROOT / "assets" / "branding" / "reelferry-icon-master.png"
    ) as master:
        assert master.mode == "RGBA"
        assert master.size == (1024, 1024)
    with Image.open(
        ROOT
        / "src"
        / "reelferry"
        / "qml"
        / "assets"
        / "reelferry-icon.png"
    ) as qml:
        assert qml.size == (512, 512)
    with Image.open(ROOT / "assets" / "reelferry.ico") as windows:
        assert windows.format == "ICO"
        assert (256, 256) in windows.info["sizes"]
