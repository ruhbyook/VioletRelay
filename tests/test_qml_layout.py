from pathlib import Path


QML = (
    Path(__file__).parents[1] / "src" / "reelferry" / "qml" / "Main.qml"
).read_text(encoding="utf-8")


def _block_after(marker: str, length: int = 500) -> str:
    start = QML.index(marker)
    return QML[start : start + length]


def test_header_actions_are_centered_independently_of_branding() -> None:
    block = _block_after("id: headerActions")

    assert 'objectName: "headerActions"' in block
    assert "anchors.horizontalCenter: parent.horizontalCenter" in block


def test_primary_transport_is_centered_independently_of_side_controls() -> None:
    block = _block_after("id: primaryTransport")

    assert 'objectName: "primaryTransport"' in block
    assert "anchors.horizontalCenter: parent.horizontalCenter" in block


def test_custom_buttons_override_material_padding_on_every_side() -> None:
    component_markers = (
        "component GlowButton: Button",
        "component RoundButtonX: Button",
        "component TransportButton: Button",
    )
    explicit_zero_padding = (
        "leftPadding: 0",
        "rightPadding: 0",
        "topPadding: 0",
        "bottomPadding: 0",
    )

    for index, marker in enumerate(component_markers):
        start = QML.index(marker)
        end = (
            QML.index(component_markers[index + 1])
            if index + 1 < len(component_markers)
            else QML.index("\n    Rectangle {", start)
        )
        block = QML[start:end]
        for declaration in explicit_zero_padding:
            assert declaration in block
