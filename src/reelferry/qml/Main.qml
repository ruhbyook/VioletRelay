import QtQuick
import QtQuick.Controls
import QtQuick.Controls.Material
import QtQuick.Layouts
import QtQuick.Dialogs
import QtQuick.Window
import QtMultimedia

ApplicationWindow {
    id: root
    width: 1280
    height: 780
    minimumWidth: 940
    minimumHeight: 620
    visible: true
    title: playback.title + " — ReelFerry"
    color: "#080B12"
    Material.theme: Material.Dark
    Material.accent: accent
    Material.background: "#171D2A"
    Material.foreground: textPrimary

    property color accent: "#7C5CFF"
    property color accentLight: "#9E8BFF"
    property color cyan: "#42D9FF"
    property color textPrimary: "#F4F6FB"
    property color textSecondary: "#9AA4B5"
    property color panel: "#E6121722"
    property bool queueVisible: true
    property bool controlsVisible: true
    property bool videoFullscreen: false
    property int visibilityBeforeFullscreen: Window.Windowed

    function toggleVideoFullscreen() {
        if (videoFullscreen) {
            videoFullscreen = false
            controlsVisible = true
            controlsHideTimer.stop()
            visibility = visibilityBeforeFullscreen
        } else {
            visibilityBeforeFullscreen = visibility === Window.Maximized ? Window.Maximized : Window.Windowed
            videoFullscreen = true
            controlsVisible = true
            visibility = Window.FullScreen
            controlsHideTimer.restart()
        }
    }

    function revealFullscreenControls() {
        if (!videoFullscreen) return
        controlsVisible = true
        controlsHideTimer.restart()
    }

    onVisibilityChanged: {
        if (visibility !== Window.FullScreen && videoFullscreen) {
            videoFullscreen = false
            controlsVisible = true
            controlsHideTimer.stop()
        }
    }

    Timer {
        id: controlsHideTimer
        interval: 2600
        repeat: false
        onTriggered: {
            if (root.videoFullscreen && !tracksPanel.opened && !fallbackDialog.opened)
                root.controlsVisible = false
        }
    }

    function formatTime(milliseconds) {
        if (!isFinite(milliseconds) || milliseconds < 0) return "0:00"
        var seconds = Math.floor(milliseconds / 1000)
        var hours = Math.floor(seconds / 3600)
        var minutes = Math.floor((seconds % 3600) / 60)
        var secs = seconds % 60
        return (hours > 0 ? hours + ":" + String(minutes).padStart(2, "0") : minutes) + ":" + String(secs).padStart(2, "0")
    }

    component GlowButton: Button {
        id: control
        implicitHeight: 40
        implicitWidth: Math.max(42, contentItem.implicitWidth + 24)
        font.family: "Segoe UI Variable"
        font.pixelSize: 14
        font.weight: Font.DemiBold
        contentItem: Text {
            text: control.text
            font: control.font
            color: control.enabled ? root.textPrimary : "#586173"
            horizontalAlignment: Text.AlignHCenter
            verticalAlignment: Text.AlignVCenter
        }
        background: Rectangle {
            radius: 12
            color: control.down ? "#4A3BA5" : control.hovered ? "#30294E" : "#1A2030"
            border.color: control.hovered ? root.accentLight : "#293044"
            border.width: 1
            Behavior on color { ColorAnimation { duration: 160 } }
        }
    }

    component RoundButtonX: Button {
        id: round
        implicitWidth: 40
        implicitHeight: 40
        font.family: "Segoe UI Variable"
        font.pixelSize: 14
        font.weight: Font.DemiBold
        contentItem: Text {
            text: round.text
            font: round.font
            color: round.enabled ? root.textPrimary : "#566071"
            horizontalAlignment: Text.AlignHCenter
            verticalAlignment: Text.AlignVCenter
        }
        background: Rectangle {
            radius: width / 2
            color: round.down ? "#4A3BA5" : round.hovered ? "#29243E" : "#151B28"
            border.color: round.activeFocus ? root.accentLight : round.hovered ? "#554A78" : "#2B3448"
            border.width: 1
            Behavior on color { ColorAnimation { duration: 170 } }
            scale: round.down ? 0.94 : 1
            Behavior on scale { NumberAnimation { duration: 120 } }
        }
        ToolTip.visible: hovered && ToolTip.text.length > 0
        ToolTip.delay: 500
    }

    component TransportButton: Button {
        id: transport
        property string glyph: ""
        property bool primary: false
        implicitWidth: primary ? 48 : 40
        implicitHeight: primary ? 48 : 40
        font.family: "Segoe Fluent Icons"
        font.pixelSize: primary ? 20 : 16
        contentItem: Text {
            text: transport.glyph
            font: transport.font
            color: transport.enabled
                   ? (transport.primary ? "white" : root.textPrimary)
                   : "#566071"
            horizontalAlignment: Text.AlignHCenter
            verticalAlignment: Text.AlignVCenter
        }
        background: Rectangle {
            radius: width / 2
            color: transport.primary
                   ? (transport.down ? "#5B3EE0" : transport.hovered ? root.accentLight : root.accent)
                   : (transport.down ? "#302650" : transport.hovered ? "#27223A" : "transparent")
            border.color: transport.primary
                          ? (transport.hovered ? "#C1B6FF" : "#947FFF")
                          : (transport.hovered ? "#5A4C80" : "transparent")
            border.width: 1
            scale: transport.down ? 0.92 : 1
            Behavior on color { ColorAnimation { duration: 150 } }
            Behavior on border.color { ColorAnimation { duration: 150 } }
            Behavior on scale { NumberAnimation { duration: 110; easing.type: Easing.OutCubic } }
        }
        ToolTip.visible: hovered && ToolTip.text.length > 0
        ToolTip.delay: 450
    }

    Rectangle {
        anchors.fill: parent
        color: "#080B12"
        gradient: Gradient {
            GradientStop { position: 0; color: "#111629" }
            GradientStop { position: 0.45; color: "#080B12" }
            GradientStop { position: 1; color: "#0B0D16" }
        }
    }

    Rectangle {
        width: 520; height: 520; radius: 260
        x: -220; y: -300
        color: "#167C5CFF"
    }

    ColumnLayout {
        anchors.fill: parent
        anchors.margins: root.videoFullscreen ? 0 : 18
        spacing: root.videoFullscreen ? 0 : 14

        RowLayout {
            visible: !root.videoFullscreen
            Layout.fillWidth: true
            Layout.preferredHeight: visible ? 48 : 0
            spacing: 12

            Image {
                source: "assets/reelferry-icon.png"
                sourceSize.width: 76
                sourceSize.height: 76
                Layout.preferredWidth: 40
                Layout.preferredHeight: 40
                fillMode: Image.PreserveAspectFit
                smooth: true
                mipmap: true
            }
            ColumnLayout {
                spacing: 0
                Text { text: "ReelFerry"; color: root.textPrimary; font.family: "Segoe UI Variable"; font.pixelSize: 17; font.weight: Font.Bold }
                Text { text: airplay.casting ? "Casting to " + airplay.castDeviceName : "Play here. Watch there."; color: airplay.casting ? root.cyan : root.textSecondary; font.pixelSize: 11 }
            }
            Item { Layout.fillWidth: true }
            GlowButton { text: "+  Open"; onClicked: fileDialog.open() }
            GlowButton {
                text: playback.urlOpening ? "Checking URL…" : "⌁  URL"
                enabled: !playback.urlOpening
                onClicked: urlDialog.open()
            }
            GlowButton {
                text: airplay.scanning ? "Scanning…" : airplay.casting ? "◉  " + airplay.castDeviceName : "◉  AirPlay"
                enabled: !playback.fallbackPreparing
                onClicked: castPanel.open()
            }
            RoundButtonX { text: "☷"; ToolTip.text: "Toggle Up Next"; onClicked: root.queueVisible = !root.queueVisible }
            RoundButtonX { text: "\u2665"; ToolTip.text: "Support development"; onClicked: supportDialog.open() }
            RoundButtonX { text: "i"; ToolTip.text: "Settings and about"; onClicked: aboutDialog.open() }
        }

        RowLayout {
            Layout.fillWidth: true
            Layout.fillHeight: true
            spacing: root.videoFullscreen ? 0 : 14

            Rectangle {
                id: stage
                Layout.fillWidth: true
                Layout.fillHeight: true
                radius: root.videoFullscreen ? 0 : 22
                color: "#05070C"
                border.color: root.videoFullscreen ? "transparent" : "#1E2636"
                clip: true

                MouseArea {
                    anchors.fill: parent
                    z: 1
                    hoverEnabled: true
                    acceptedButtons: Qt.NoButton
                    cursorShape: root.videoFullscreen && !root.controlsVisible ? Qt.BlankCursor : Qt.ArrowCursor
                    onPositionChanged: root.revealFullscreenControls()
                }

                VideoOutput {
                    id: videoOutput
                    anchors.fill: parent
                    fillMode: VideoOutput.PreserveAspectFit
                    visible: playback.source.length > 0 && !airplay.casting && !airplay.preparing && !playback.fallbackPreparing
                    Component.onCompleted: playback.attachVideoOutput(videoOutput)
                }

                DropArea {
                    anchors.fill: parent
                    onEntered: function(drag) { drag.accepted = true }
                    onDropped: function(drop) { playback.openFiles(drop.urls); drop.acceptProposedAction() }
                }

                Column {
                    anchors.centerIn: parent
                    spacing: 16
                    visible: playback.source.length === 0 && !playback.urlOpening && !airplay.casting && !airplay.preparing && !playback.fallbackPreparing
                    Image {
                        anchors.horizontalCenter: parent.horizontalCenter
                        width: 96
                        height: 96
                        source: "assets/reelferry-icon.png"
                        sourceSize.width: 192
                        sourceSize.height: 192
                        fillMode: Image.PreserveAspectFit
                        smooth: true
                        mipmap: true
                    }
                    Text { anchors.horizontalCenter: parent.horizontalCenter; text: "Your screen, your cinema"; color: root.textPrimary; font.pixelSize: 25; font.weight: Font.DemiBold }
                    Text { anchors.horizontalCenter: parent.horizontalCenter; text: "Drop media here, open a file, or paste a direct media URL"; color: root.textSecondary; font.pixelSize: 13 }
                    Row {
                        anchors.horizontalCenter: parent.horizontalCenter; spacing: 10
                        GlowButton { text: "Open media"; onClicked: fileDialog.open() }
                        GlowButton { text: "Paste URL"; onClicked: urlDialog.open() }
                    }
                }

                Column {
                    anchors.centerIn: parent
                    spacing: 14
                    visible: playback.urlOpening
                    BusyIndicator {
                        anchors.horizontalCenter: parent.horizontalCenter
                        running: visible
                    }
                    Text {
                        anchors.horizontalCenter: parent.horizontalCenter
                        text: "Checking direct media URL…"
                        color: root.textPrimary
                        font.pixelSize: 18
                        font.weight: Font.DemiBold
                    }
                    Text {
                        anchors.horizontalCenter: parent.horizontalCenter
                        text: "Verifying that this is media rather than a web page"
                        color: root.textSecondary
                        font.pixelSize: 12
                    }
                }

                Column {
                    anchors.centerIn: parent
                    width: Math.min(540, parent.width - 80)
                    spacing: 14
                    visible: airplay.casting
                    Rectangle {
                        anchors.horizontalCenter: parent.horizontalCenter
                        width: 106; height: 106; radius: 53
                        color: "#202A3C"
                        border.color: root.cyan
                        border.width: 2
                        Text { anchors.centerIn: parent; text: "◉"; color: root.cyan; font.pixelSize: 38 }
                    }
                    Text { anchors.horizontalCenter: parent.horizontalCenter; text: "Playing on " + airplay.castDeviceName; color: root.textPrimary; font.pixelSize: 24; font.weight: Font.DemiBold }
                    Text { anchors.horizontalCenter: parent.horizontalCenter; text: playback.title; color: root.textSecondary; font.pixelSize: 14; elide: Text.ElideRight; width: 500; horizontalAlignment: Text.AlignHCenter }
                    Row {
                        anchors.horizontalCenter: parent.horizontalCenter; spacing: 10
                        GlowButton { text: airplay.castState === "paused" ? "Resume" : "Pause"; onClicked: airplay.playPause() }
                        GlowButton { text: "Continue here"; onClicked: airplay.continueLocally() }
                        GlowButton { text: "Stop casting"; onClicked: airplay.stopCasting() }
                    }
                    RowLayout {
                        anchors.horizontalCenter: parent.horizontalCenter
                        width: Math.min(360, parent.width)
                        visible: airplay.receiverVolumeAvailable
                        spacing: 10
                        Text {
                            text: "Apple TV volume"
                            color: root.textSecondary
                            font.pixelSize: 12
                        }
                        Slider {
                            id: receiverVolume
                            Layout.fillWidth: true
                            from: 0
                            to: 100
                            value: pressed ? value : airplay.receiverVolume
                            onPressedChanged: {
                                if (!pressed)
                                    airplay.setReceiverVolume(value)
                            }
                        }
                        Text {
                            text: Math.round(receiverVolume.value) + "%"
                            color: root.textSecondary
                            font.pixelSize: 11
                        }
                    }
                }

                Column {
                    anchors.centerIn: parent
                    width: Math.min(500, parent.width - 80)
                    spacing: 14
                    visible: airplay.preparing || airplay.connecting
                    Text {
                        anchors.horizontalCenter: parent.horizontalCenter
                        text: airplay.connecting ? "Connecting to " + airplay.castDeviceName : airplay.preparationStatus
                        color: root.textPrimary
                        font.pixelSize: 22
                        font.weight: Font.DemiBold
                    }
                    Text {
                        anchors.horizontalCenter: parent.horizontalCenter
                        visible: airplay.connecting
                        text: "Waiting for Apple TV to request and start the video..."
                        color: root.textSecondary
                        font.pixelSize: 13
                    }
                    ProgressBar {
                        width: parent.width
                        indeterminate: airplay.connecting
                        value: airplay.preparationProgress
                    }
                    Text {
                        anchors.horizontalCenter: parent.horizontalCenter
                        visible: !airplay.connecting
                        text: {
                            var percent = airplay.preparationProgress * 100
                            if (percent < 1) return percent.toFixed(2) + "%"
                            if (percent < 10) return percent.toFixed(1) + "%"
                            return Math.round(percent) + "%"
                        }
                        color: root.textSecondary
                    }
                    GlowButton {
                        anchors.horizontalCenter: parent.horizontalCenter
                        visible: !airplay.connecting
                        text: "Cancel"
                        onClicked: airplay.cancelPreparation()
                    }
                }

                Column {
                    anchors.centerIn: parent
                    width: Math.min(500, parent.width - 80)
                    spacing: 14
                    visible: playback.fallbackPreparing
                    Text { anchors.horizontalCenter: parent.horizontalCenter; text: playback.fallbackStatus; color: root.textPrimary; font.pixelSize: 22; font.weight: Font.DemiBold }
                    ProgressBar { width: parent.width; value: playback.fallbackProgress }
                    Text {
                        anchors.horizontalCenter: parent.horizontalCenter
                        text: Math.round(playback.fallbackProgress * 100) + "%"
                        color: root.textSecondary
                    }
                    GlowButton { anchors.horizontalCenter: parent.horizontalCenter; text: "Cancel"; onClicked: playback.cancelLocalFallback() }
                }

                Rectangle {
                    anchors.horizontalCenter: parent.horizontalCenter
                    anchors.bottom: controlsPanel.visible ? controlsPanel.top : parent.bottom
                    anchors.bottomMargin: controlsPanel.visible ? 18 : 36
                    width: Math.min(stage.width - 80, subtitleLabel.implicitWidth + 36)
                    height: subtitleLabel.implicitHeight + 18
                    radius: 8
                    color: "#CC05070C"
                    visible: playback.subtitleText.length > 0 && !airplay.casting
                    Text {
                        id: subtitleLabel
                        anchors.centerIn: parent
                        width: Math.min(760, stage.width - 100)
                        text: playback.subtitleText
                        color: "white"
                        font.pixelSize: 21
                        font.weight: Font.DemiBold
                        wrapMode: Text.Wrap
                        horizontalAlignment: Text.AlignHCenter
                    }
                }

                Rectangle {
                    id: controlsPanel
                    z: 10
                    anchors.left: parent.left
                    anchors.right: parent.right
                    anchors.bottom: parent.bottom
                    anchors.margins: 16
                    height: 120
                    radius: 20
                    color: "#F0101622"
                    border.color: "#303A50"
                    border.width: 1
                    visible: playback.source.length > 0 && !airplay.preparing && !playback.fallbackPreparing && (!root.videoFullscreen || root.controlsVisible)

                    ColumnLayout {
                        anchors.fill: parent
                        anchors.margins: 14
                        spacing: 5
                        Slider {
                            id: timeline
                            Layout.fillWidth: true
                            Layout.preferredHeight: 24
                            from: 0
                            to: airplay.casting ? Math.max(1, airplay.castDuration * 1000) : Math.max(1, playback.duration)
                            value: pressed ? value : (airplay.casting ? airplay.castPosition * 1000 : playback.position)
                            onMoved: {
                                if (!airplay.casting)
                                    playback.seek(value)
                            }
                            onPressedChanged: {
                                if (!pressed && airplay.casting)
                                    airplay.seek(Math.round(value / 1000))
                            }
                            background: Rectangle {
                                x: timeline.leftPadding
                                y: timeline.topPadding + timeline.availableHeight / 2 - height / 2
                                width: timeline.availableWidth
                                height: 4
                                radius: 2
                                color: "#343C52"
                                Rectangle {
                                    width: timeline.visualPosition * parent.width
                                    height: parent.height
                                    radius: parent.radius
                                    gradient: Gradient {
                                        GradientStop { position: 0; color: root.accent }
                                        GradientStop { position: 1; color: root.cyan }
                                    }
                                }
                            }
                            handle: Rectangle {
                                x: timeline.leftPadding + timeline.visualPosition * (timeline.availableWidth - width)
                                y: timeline.topPadding + timeline.availableHeight / 2 - height / 2
                                width: timeline.pressed ? 16 : 14
                                height: width
                                radius: width / 2
                                color: timeline.pressed ? root.cyan : root.accentLight
                                border.color: "#D8D1FF"
                                border.width: 1
                                Behavior on width { NumberAnimation { duration: 100 } }
                                Behavior on color { ColorAnimation { duration: 120 } }
                            }
                        }
                        RowLayout {
                            Layout.fillWidth: true
                            spacing: 9
                            Rectangle {
                                implicitWidth: transportRow.implicitWidth + 10
                                implicitHeight: 52
                                Layout.preferredWidth: implicitWidth
                                Layout.preferredHeight: implicitHeight
                                radius: height / 2
                                color: "#121824"
                                border.color: "#293349"
                                RowLayout {
                                    id: transportRow
                                    anchors.centerIn: parent
                                    spacing: 2
                                    TransportButton {
                                        glyph: "\uE892"
                                        ToolTip.text: "Previous"
                                        onClicked: playback.previous()
                                    }
                                    TransportButton {
                                        primary: true
                                        glyph: (airplay.casting ? airplay.castState !== "paused" : playback.playing) ? "\uE769" : "\uE768"
                                        ToolTip.text: (airplay.casting ? airplay.castState !== "paused" : playback.playing) ? "Pause" : "Play"
                                        onClicked: airplay.casting ? airplay.playPause() : playback.playPause()
                                    }
                                    TransportButton {
                                        glyph: "\uE893"
                                        ToolTip.text: "Next"
                                        onClicked: playback.next()
                                    }
                                }
                            }
                            Text {
                                text: root.formatTime(airplay.casting ? airplay.castPosition * 1000 : playback.position)
                                      + "  /  "
                                      + root.formatTime(airplay.casting ? airplay.castDuration * 1000 : playback.duration)
                                color: root.textSecondary
                                font.family: "Cascadia Mono"
                                font.pixelSize: 11
                            }
                            Item { Layout.fillWidth: true }
                            RoundButtonX {
                                text: playback.muted ? "\uE74F" : "\uE767"
                                font.family: "Segoe Fluent Icons"
                                font.pixelSize: 16
                                ToolTip.text: playback.muted ? "Unmute" : "Mute"
                                visible: !airplay.casting
                                onClicked: playback.toggleMute()
                            }
                            Slider {
                                id: volumeSlider
                                visible: !airplay.casting && stage.width > 720
                                Layout.preferredWidth: 105
                                from: 0
                                to: 1
                                value: playback.volume
                                onMoved: playback.setVolume(value)
                                background: Rectangle {
                                    x: volumeSlider.leftPadding
                                    y: volumeSlider.topPadding + volumeSlider.availableHeight / 2 - height / 2
                                    width: volumeSlider.availableWidth
                                    height: 3
                                    radius: 2
                                    color: "#343C52"
                                    Rectangle {
                                        width: volumeSlider.visualPosition * parent.width
                                        height: parent.height
                                        radius: parent.radius
                                        color: root.accentLight
                                    }
                                }
                                handle: Rectangle {
                                    x: volumeSlider.leftPadding + volumeSlider.visualPosition * (volumeSlider.availableWidth - width)
                                    y: volumeSlider.topPadding + volumeSlider.availableHeight / 2 - height / 2
                                    width: 12
                                    height: 12
                                    radius: 6
                                    color: root.accentLight
                                }
                            }
                            ComboBox {
                                id: speedControl
                                visible: !airplay.casting
                                property var rates: [0.5, 0.75, 1, 1.25, 1.5, 2]
                                model: ["0.5×", "0.75×", "1×", "1.25×", "1.5×", "2×"]
                                currentIndex: Math.max(0, rates.indexOf(playback.playbackRate))
                                Layout.preferredWidth: 88
                                Layout.preferredHeight: 38
                                leftPadding: 14
                                rightPadding: 30
                                font.family: "Segoe UI Variable"
                                font.pixelSize: 13
                                font.weight: Font.DemiBold
                                onActivated: playback.setPlaybackRate(rates[currentIndex])
                                contentItem: Text {
                                    leftPadding: speedControl.leftPadding
                                    rightPadding: speedControl.rightPadding
                                    text: speedControl.displayText
                                    font: speedControl.font
                                    color: root.textPrimary
                                    verticalAlignment: Text.AlignVCenter
                                }
                                indicator: Text {
                                    x: speedControl.width - width - 13
                                    y: (speedControl.height - height) / 2 - 1
                                    text: "▾"
                                    color: speedControl.hovered ? root.accentLight : root.textSecondary
                                    font.family: "Segoe UI Symbol"
                                    font.pixelSize: 14
                                }
                                background: Rectangle {
                                    radius: height / 2
                                    color: speedControl.down ? "#302650" : speedControl.hovered ? "#242039" : "#171D2A"
                                    border.color: speedControl.activeFocus ? root.accentLight : speedControl.hovered ? "#51447B" : "#2B3244"
                                    border.width: 1
                                    Behavior on color { ColorAnimation { duration: 160 } }
                                    Behavior on border.color { ColorAnimation { duration: 160 } }
                                }
                            }
                            RoundButtonX { text: "CC"; visible: !airplay.casting; ToolTip.text: "Audio and subtitle tracks"; onClicked: tracksPanel.open() }
                            RoundButtonX {
                                text: root.videoFullscreen ? "\uE73F" : "\uE740"
                                font.family: "Segoe Fluent Icons"
                                font.pixelSize: 16
                                ToolTip.text: root.videoFullscreen ? "Exit full screen" : "Full screen"
                                onClicked: root.toggleVideoFullscreen()
                            }
                        }
                    }
                }
            }

            Rectangle {
                Layout.preferredWidth: root.queueVisible && !root.videoFullscreen ? 330 : 0
                Layout.fillHeight: true
                visible: width > 0
                radius: 20
                color: root.panel
                border.color: "#293145"
                clip: true
                Behavior on Layout.preferredWidth { NumberAnimation { duration: 200; easing.type: Easing.OutCubic } }

                ColumnLayout {
                    anchors.fill: parent
                    anchors.margins: 14
                    spacing: 10
                    RowLayout {
                        Layout.fillWidth: true
                        Text { text: "Up Next"; color: root.textPrimary; font.pixelSize: 18; font.weight: Font.DemiBold }
                        Item { Layout.fillWidth: true }
                        GlowButton { text: "Clear"; onClicked: queueModel.clear() }
                    }
                    ListView {
                        id: queueView
                        Layout.fillWidth: true
                        Layout.fillHeight: true
                        model: queueModel
                        spacing: 7
                        clip: true
                        delegate: Rectangle {
                            id: queueDelegate
                            required property int index
                            required property string title
                            required property string kind
                            required property bool isCurrent
                            width: queueView.width
                            height: 66
                            radius: 13
                            color: isCurrent ? "#332C58" : itemHover.hovered ? "#202738" : "#151A26"
                            border.color: isCurrent ? root.accentLight : "#242C3D"
                            Behavior on color { ColorAnimation { duration: 160 } }
                            RowLayout {
                                anchors.fill: parent; anchors.margins: 10; spacing: 10
                                Rectangle {
                                    width: 42; height: 42; radius: 10
                                    color: isCurrent ? root.accent : "#252D40"
                                    Text { anchors.centerIn: parent; text: kind === "url" ? "⌁" : "▶"; color: "white" }
                                }
                                ColumnLayout {
                                    Layout.fillWidth: true; spacing: 2
                                    Text { Layout.fillWidth: true; text: title; color: root.textPrimary; elide: Text.ElideRight; font.pixelSize: 13; font.weight: Font.DemiBold }
                                    Text { text: kind === "url" ? "Network media" : "Local media"; color: root.textSecondary; font.pixelSize: 10 }
                                }
                                Button { text: "×"; flat: true; onClicked: queueModel.remove(index) }
                            }
                            HoverHandler { id: itemHover }
                            TapHandler { onTapped: playback.playIndex(queueDelegate.index) }
                        }
                        footer: Item {
                            width: queueView.width; height: queueModel.count === 0 ? 140 : 12
                            Text { anchors.centerIn: parent; visible: queueModel.count === 0; text: "Your session queue is empty"; color: root.textSecondary }
                        }
                    }
                    GlowButton { Layout.fillWidth: true; text: "+ Add media"; onClicked: fileDialog.open() }
                }
            }
        }
    }

    Popup {
        id: tracksPanel
        x: Math.max(20, root.width - width - (root.queueVisible ? 372 : 28))
        y: Math.max(70, root.height - height - 148)
        width: 360
        height: 260
        modal: true
        focus: true
        closePolicy: Popup.CloseOnEscape | Popup.CloseOnPressOutside
        background: Rectangle { radius: 20; color: "#F2161B28"; border.color: "#424D68" }
        contentItem: ColumnLayout {
            spacing: 10
            Text { text: "Tracks"; color: root.textPrimary; font.pixelSize: 19; font.weight: Font.DemiBold }
            Text { text: "Audio"; color: root.textSecondary; font.pixelSize: 11 }
            ComboBox {
                Layout.fillWidth: true
                enabled: playback.audioTracks.length > 0
                model: playback.audioTracks
                textRole: "label"
                valueRole: "index"
                currentIndex: playback.audioTrackModelIndex
                displayText: enabled ? currentText : "No audio tracks"
                onActivated: playback.selectAudioTrack(currentValue)
            }
            Text { text: "Subtitles"; color: root.textSecondary; font.pixelSize: 11 }
            ComboBox {
                Layout.fillWidth: true
                model: playback.subtitleTracks
                textRole: "label"
                valueRole: "value"
                currentIndex: playback.subtitleTrackModelIndex
                onActivated: playback.selectSubtitleTrack(currentValue)
            }
            RowLayout {
                Layout.fillWidth: true
                GlowButton {
                    Layout.fillWidth: true
                    text: "Add subtitle file"
                    onClicked: { tracksPanel.close(); subtitleDialog.open() }
                }
                GlowButton { text: "Off"; onClicked: playback.selectSubtitleTrack("") }
            }
        }
    }

    Popup {
        id: castPanel
        x: root.width - width - 28
        y: 76
        width: 380
        height: Math.min(500, root.height - 110)
        modal: true
        focus: true
        closePolicy: Popup.CloseOnEscape | Popup.CloseOnPressOutside
        background: Rectangle { radius: 20; color: "#F2161B28"; border.color: "#424D68" }
        contentItem: ColumnLayout {
            spacing: 12
            RowLayout {
                Layout.fillWidth: true
                Text { text: "Choose an Apple TV"; color: root.textPrimary; font.pixelSize: 19; font.weight: Font.DemiBold }
                Item { Layout.fillWidth: true }
                GlowButton { text: airplay.scanning ? "Scanning…" : "Rescan"; enabled: !airplay.scanning; onClicked: airplay.scan() }
            }
            Text { Layout.fillWidth: true; text: "Devices must be on the same private network."; color: root.textSecondary; wrapMode: Text.Wrap }
            ListView {
                id: deviceView
                Layout.fillWidth: true
                Layout.fillHeight: true
                model: airplay.deviceModel
                spacing: 8
                delegate: Rectangle {
                    id: deviceDelegate
                    required property int index
                    required property string name
                    required property string address
                    required property string deviceModel
                    required property bool paired
                    required property bool preferred
                    width: deviceView.width; height: 78; radius: 14
                    color: deviceHover.hovered ? "#262D41" : preferred ? "#211D38" : "#181E2C"
                    border.color: preferred ? root.accentLight : paired ? "#386A75" : "#30384D"
                    RowLayout {
                        anchors.fill: parent; anchors.margins: 11; spacing: 11
                        Rectangle { width: 46; height: 46; radius: 13; color: "#243346"; Text { anchors.centerIn: parent; text: "▣"; color: root.cyan; font.pixelSize: 20 } }
                        ColumnLayout {
                            Layout.fillWidth: true; spacing: 1
                            Text { text: name; color: root.textPrimary; font.weight: Font.DemiBold; font.pixelSize: 14 }
                            Text { text: deviceModel + "  ·  " + address; color: root.textSecondary; font.pixelSize: 10 }
                            Text {
                                text: (preferred ? "Preferred  ·  " : "") + (paired ? "Paired" : "Pairing required")
                                color: paired ? root.cyan : "#E7B86A"
                                font.pixelSize: 10
                            }
                        }
                        GlowButton { text: paired ? "Cast" : "Pair"; onClicked: { paired ? airplay.castTo(index) : airplay.beginPair(index); castPanel.close() } }
                    }
                    HoverHandler { id: deviceHover }
                }
                footer: Item {
                    width: deviceView.width; height: deviceView.count === 0 ? 150 : 10
                    Text { anchors.centerIn: parent; visible: deviceView.count === 0 && !airplay.scanning; text: "No Apple TV found\nCheck Wi-Fi and Windows Firewall"; color: root.textSecondary; horizontalAlignment: Text.AlignHCenter }
                }
            }
        }
    }

    Dialog {
        id: pairDialog
        anchors.centerIn: parent
        width: 420
        modal: true
        closePolicy: Popup.NoAutoClose
        visible: airplay.pairing && airplay.pairingInstruction.length > 0
        title: "Pair " + airplay.pairingProtocol
        background: Rectangle { radius: 20; color: "#F2181D2B"; border.color: root.accent }
        contentItem: ColumnLayout {
            spacing: 14
            Text { Layout.fillWidth: true; text: airplay.pairingInstruction; color: root.textPrimary; font.pixelSize: 16; wrapMode: Text.Wrap; horizontalAlignment: Text.AlignHCenter }
            TextField { id: pinField; Layout.alignment: Qt.AlignHCenter; Layout.preferredWidth: 220; placeholderText: "PIN"; inputMethodHints: Qt.ImhDigitsOnly; horizontalAlignment: Text.AlignHCenter; font.pixelSize: 25; maximumLength: 8; onAccepted: airplay.submitPin(text) }
            GlowButton { Layout.alignment: Qt.AlignHCenter; text: pinField.text.length > 0 ? "Pair" : "Continue"; onClicked: { airplay.submitPin(pinField.text); pinField.clear() } }
        }
    }

    Dialog {
        id: resumeDialog
        anchors.centerIn: parent
        width: 480
        modal: true
        closePolicy: Popup.NoAutoClose
        title: "Continue where you left off?"
        property string mediaTitle: ""
        property string savedPosition: ""
        background: Rectangle { radius: 18; color: "#F2181D2B"; border.color: root.accent }
        contentItem: ColumnLayout {
            spacing: 18
            Text {
                Layout.fillWidth: true
                text: "Resume “" + resumeDialog.mediaTitle + "” from " + resumeDialog.savedPosition + "?"
                color: root.textPrimary
                wrapMode: Text.Wrap
                font.pixelSize: 15
            }
            Text {
                Layout.fillWidth: true
                text: "Your position is saved automatically while listening or watching."
                color: root.textSecondary
                wrapMode: Text.Wrap
                font.pixelSize: 12
            }
            RowLayout {
                Layout.fillWidth: true
                spacing: 10
                GlowButton {
                    Layout.fillWidth: true
                    text: "Start over"
                    onClicked: {
                        resumeDialog.close()
                        playback.startFromBeginning()
                    }
                }
                GlowButton {
                    Layout.fillWidth: true
                    text: "Resume at " + resumeDialog.savedPosition
                    onClicked: {
                        resumeDialog.close()
                        playback.resumeFromSavedPosition()
                    }
                }
            }
        }
    }

    Dialog {
        id: aboutDialog
        anchors.centerIn: parent
        width: 560
        modal: true
        title: "Settings and About"
        standardButtons: Dialog.Ok
        onOpened: {
            if (windowsIntegration) windowsIntegration.refresh()
            if (appSettings) appSettings.refresh()
        }
        background: Rectangle { radius: 18; color: "#F2181D2B"; border.color: root.accent }
        contentItem: ColumnLayout {
            spacing: 12
            Text { text: "ReelFerry " + Qt.application.version; color: root.textPrimary; font.pixelSize: 20; font.weight: Font.DemiBold }
            Text { text: "Play here. Watch there.  ·  Formerly xMediaPlayerx"; color: root.textSecondary; font.pixelSize: 12 }
            Rectangle { Layout.fillWidth: true; height: 1; color: "#30384D" }
            Text { text: "Media tools"; color: root.textPrimary; font.pixelSize: 15; font.weight: Font.DemiBold }
            RowLayout {
                Layout.fillWidth: true
                spacing: 10
                Text {
                    Layout.fillWidth: true
                    text: mediaTools ? mediaTools.status : ""
                    color: mediaTools && mediaTools.available ? root.cyan : root.textSecondary
                    wrapMode: Text.Wrap
                    font.pixelSize: 12
                }
                GlowButton {
                    visible: mediaTools && !mediaTools.available
                    text: mediaTools && mediaTools.downloading ? "Installing…" : "Install"
                    enabled: mediaTools && !mediaTools.downloading
                    onClicked: mediaToolsDialog.open()
                }
            }
            Rectangle { Layout.fillWidth: true; height: 1; color: "#30384D" }
            Text { text: "Prepared cast cache"; color: root.textPrimary; font.pixelSize: 15; font.weight: Font.DemiBold }
            RowLayout {
                Layout.fillWidth: true
                spacing: 10
                Text {
                    text: "Limit"
                    color: root.textSecondary
                    font.pixelSize: 12
                }
                SpinBox {
                    id: cacheLimitControl
                    from: 1
                    to: 1000
                    value: appSettings ? appSettings.cacheLimitGb : 20
                    editable: true
                }
                Text {
                    text: "GB  ·  Currently " + (appSettings ? appSettings.cacheUsageText : "0 bytes")
                    color: root.textSecondary
                    font.pixelSize: 12
                    Layout.fillWidth: true
                }
                GlowButton {
                    text: "Apply"
                    onClicked: {
                        if (appSettings)
                            appSettings.setCacheLimitGb(cacheLimitControl.value)
                    }
                }
                GlowButton {
                    text: "Clear cache"
                    onClicked: {
                        if (appSettings)
                            appSettings.clearCastCache()
                    }
                }
            }
            Text {
                Layout.fillWidth: true
                visible: appSettings && appSettings.cacheStatus.length > 0
                text: appSettings ? appSettings.cacheStatus : ""
                color: root.cyan
                font.pixelSize: 11
            }
            Rectangle { Layout.fillWidth: true; height: 1; color: "#30384D" }
            Text { text: "Windows file integration"; color: root.textPrimary; font.pixelSize: 15; font.weight: Font.DemiBold }
            Text {
                Layout.fillWidth: true
                text: windowsIntegration ? windowsIntegration.statusText : ""
                color: windowsIntegration && windowsIntegration.needsRepair ? "#E7B86A" : root.textSecondary
                wrapMode: Text.Wrap
                font.pixelSize: 12
            }
            GlowButton {
                Layout.fillWidth: true
                text: windowsIntegration ? windowsIntegration.openWithActionText : ""
                enabled: windowsIntegration && windowsIntegration.available
                         && (!windowsIntegration.openWithRegistered || windowsIntegration.needsRepair)
                onClicked: { if (windowsIntegration) windowsIntegration.registerForOpenWith() }
            }
            GlowButton {
                Layout.fillWidth: true
                text: windowsIntegration ? windowsIntegration.actionText : ""
                enabled: windowsIntegration && windowsIntegration.available
                onClicked: { if (windowsIntegration) windowsIntegration.registerAndChooseDefaults() }
            }
            GlowButton {
                Layout.fillWidth: true
                visible: windowsIntegration && windowsIntegration.openWithRegistered
                text: "Remove Windows file integration"
                onClicked: { if (windowsIntegration) windowsIntegration.unregister() }
            }
            Text {
                Layout.fillWidth: true
                visible: windowsIntegration && windowsIntegration.available
                text: "Open with registration happens automatically and never changes defaults. Windows requires your confirmation before ReelFerry becomes a default player."
                color: root.textSecondary
                wrapMode: Text.Wrap
                font.pixelSize: 11
            }
            GlowButton {
                Layout.fillWidth: true
                text: "\u2665  Support development"
                onClicked: supportDialog.open()
            }
            GlowButton {
                Layout.fillWidth: true
                text: "Open diagnostic log folder"
                onClicked: {
                    if (appSettings)
                        appSettings.openDiagnosticsFolder()
                }
            }
            Rectangle { Layout.fillWidth: true; height: 1; color: "#30384D" }
            Text {
                Layout.fillWidth: true
                text: "Free software licensed under GPL-3.0-or-later. AirPlay support is unofficial and reverse-engineered. ReelFerry is not affiliated with, endorsed by, or certified by Apple. All features are free; donations never unlock functionality."
                color: root.textSecondary
                wrapMode: Text.Wrap
                font.pixelSize: 13
            }
            Text {
                Layout.fillWidth: true
                text: "The portable folder includes LICENSE, THIRD_PARTY_NOTICES.md, FFMPEG_SOURCE.md, and dependency license texts."
                color: root.textSecondary
                wrapMode: Text.Wrap
                font.pixelSize: 12
            }
        }
    }

    Dialog {
        id: supportDialog
        anchors.centerIn: parent
        width: Math.min(700, root.width - 36)
        height: Math.min(680, root.height - 36)
        modal: true
        title: "Support ReelFerry"
        standardButtons: Dialog.Close
        onOpened: {
            if (appSettings)
                appSettings.clearSupportStatus()
        }
        background: Rectangle {
            radius: 18
            color: "#FA181D2B"
            border.color: root.accent
            border.width: 1
        }
        contentItem: ColumnLayout {
            spacing: 12

            Text {
                Layout.fillWidth: true
                text: "ReelFerry is free software. Optional tips help support testing and development; they never unlock features."
                color: root.textSecondary
                wrapMode: Text.Wrap
                font.pixelSize: 13
            }

            RowLayout {
                Layout.fillWidth: true
                Layout.fillHeight: true
                spacing: 14

                Rectangle {
                    Layout.fillWidth: true
                    Layout.fillHeight: true
                    Layout.minimumHeight: 350
                    radius: 16
                    color: "#101621"
                    border.color: "#303A50"
                    border.width: 1

                    ColumnLayout {
                        anchors.fill: parent
                        anchors.margins: 16
                        spacing: 7

                        Text {
                            Layout.alignment: Qt.AlignHCenter
                            text: "Bitcoin"
                            color: root.textPrimary
                            font.pixelSize: 18
                            font.weight: Font.DemiBold
                        }
                        Text {
                            Layout.alignment: Qt.AlignHCenter
                            text: "BTC \u00B7 Bitcoin network"
                            color: "#F2A900"
                            font.pixelSize: 12
                            font.weight: Font.DemiBold
                        }
                        Image {
                            Layout.alignment: Qt.AlignHCenter
                            Layout.preferredWidth: 180
                            Layout.preferredHeight: 180
                            source: "assets/support-bitcoin.png"
                            fillMode: Image.PreserveAspectFit
                            smooth: false
                        }
                        Text {
                            Layout.fillWidth: true
                            text: appSettings ? appSettings.bitcoinAddress : ""
                            color: root.textSecondary
                            font.family: "Consolas"
                            font.pixelSize: 11
                            horizontalAlignment: Text.AlignHCenter
                            wrapMode: Text.WrapAnywhere
                        }
                        Item { Layout.fillHeight: true }
                        GlowButton {
                            Layout.fillWidth: true
                            text: "Copy Bitcoin address"
                            onClicked: {
                                if (appSettings)
                                    appSettings.copyBitcoinAddress()
                            }
                        }
                    }
                }

                Rectangle {
                    Layout.fillWidth: true
                    Layout.fillHeight: true
                    Layout.minimumHeight: 350
                    radius: 16
                    color: "#101621"
                    border.color: "#303A50"
                    border.width: 1

                    ColumnLayout {
                        anchors.fill: parent
                        anchors.margins: 16
                        spacing: 7

                        Text {
                            Layout.alignment: Qt.AlignHCenter
                            text: "Ethereum / USDC"
                            color: root.textPrimary
                            font.pixelSize: 18
                            font.weight: Font.DemiBold
                        }
                        Text {
                            Layout.alignment: Qt.AlignHCenter
                            text: "ETH or USDC \u00B7 Ethereum Mainnet only"
                            color: "#8C8CFF"
                            font.pixelSize: 12
                            font.weight: Font.DemiBold
                        }
                        Image {
                            Layout.alignment: Qt.AlignHCenter
                            Layout.preferredWidth: 180
                            Layout.preferredHeight: 180
                            source: "assets/support-ethereum.png"
                            fillMode: Image.PreserveAspectFit
                            smooth: false
                        }
                        Text {
                            Layout.fillWidth: true
                            text: appSettings ? appSettings.ethereumAddress : ""
                            color: root.textSecondary
                            font.family: "Consolas"
                            font.pixelSize: 11
                            horizontalAlignment: Text.AlignHCenter
                            wrapMode: Text.WrapAnywhere
                        }
                        Item { Layout.fillHeight: true }
                        GlowButton {
                            Layout.fillWidth: true
                            text: "Copy Ethereum address"
                            onClicked: {
                                if (appSettings)
                                    appSettings.copyEthereumAddress()
                            }
                        }
                    }
                }
            }

            Text {
                Layout.fillWidth: true
                visible: appSettings && appSettings.supportStatus.length > 0
                text: appSettings ? appSettings.supportStatus : ""
                color: root.cyan
                horizontalAlignment: Text.AlignHCenter
                font.pixelSize: 12
                font.weight: Font.DemiBold
            }
            Text {
                Layout.fillWidth: true
                text: "Check the asset and network before sending. Crypto transfers are irreversible. This screen never asks for or accepts a seed phrase, private key, or wallet connection."
                color: "#E7B86A"
                wrapMode: Text.Wrap
                horizontalAlignment: Text.AlignHCenter
                font.pixelSize: 12
            }
        }
    }

    Dialog {
        id: fallbackDialog
        anchors.centerIn: parent
        width: 520
        modal: true
        title: "Create compatibility copy?"
        standardButtons: Dialog.Yes | Dialog.No
        property string message: ""
        onAccepted: playback.prepareLocalFallback()
        background: Rectangle { radius: 18; color: "#F2181D2B"; border.color: root.accent }
        Text {
            width: parent.width
            text: fallbackDialog.message
            color: root.textPrimary
            wrapMode: Text.Wrap
            font.pixelSize: 14
        }
    }

    Dialog {
        id: urlDialog
        anchors.centerIn: parent
        width: 560
        modal: true
        title: "Open direct media URL"
        standardButtons: Dialog.Open | Dialog.Cancel
        onAccepted: { playback.openUrl(urlField.text); urlField.clear() }
        background: Rectangle { radius: 18; color: "#F2181D2B"; border.color: "#3D465F" }
        TextField { id: urlField; width: parent.width; placeholderText: "https://example.com/video.mp4 or stream.m3u8"; selectByMouse: true }
    }

    Dialog {
        id: recoveryDialog
        anchors.centerIn: parent
        width: 520
        modal: true
        closePolicy: Popup.NoAutoClose
        title: "Apple TV connection lost"
        property string message: ""
        background: Rectangle { radius: 18; color: "#F2181D2B"; border.color: "#E7B86A" }
        contentItem: ColumnLayout {
            spacing: 16
            Text {
                Layout.fillWidth: true
                text: recoveryDialog.message
                color: root.textPrimary
                wrapMode: Text.Wrap
                font.pixelSize: 14
            }
            Text {
                Layout.fillWidth: true
                text: "Local playback is still paused at the last confirmed Apple TV position."
                color: root.textSecondary
                wrapMode: Text.Wrap
                font.pixelSize: 12
            }
            RowLayout {
                Layout.fillWidth: true
                spacing: 10
                GlowButton {
                    Layout.fillWidth: true
                    text: "Continue here"
                    onClicked: {
                        recoveryDialog.close()
                        airplay.continueAfterDisconnect()
                    }
                }
                GlowButton {
                    Layout.fillWidth: true
                    text: "Retry casting"
                    onClicked: {
                        recoveryDialog.close()
                        airplay.retryCasting()
                    }
                }
            }
        }
    }

    Dialog {
        id: mediaToolsDialog
        anchors.centerIn: parent
        width: 540
        modal: true
        closePolicy: mediaTools && mediaTools.downloading
                     ? Popup.NoAutoClose
                     : Popup.CloseOnEscape
        title: "Install verified media tools"
        background: Rectangle { radius: 18; color: "#F2181D2B"; border.color: root.accent }
        contentItem: ColumnLayout {
            spacing: 16
            Text {
                Layout.fillWidth: true
                text: "Casting, subtitles, media inspection, and compatibility conversion require FFmpeg. ReelFerry will download the verified 8.1.2 tools directly from the Windows build provider linked by ffmpeg.org (about 105 MB)."
                color: root.textPrimary
                wrapMode: Text.Wrap
                font.pixelSize: 14
            }
            Text {
                Layout.fillWidth: true
                text: "The download is optional and only starts when you choose Install. Its SHA-256 and both executable hashes are checked before use."
                color: root.textSecondary
                wrapMode: Text.Wrap
                font.pixelSize: 12
            }
            ProgressBar {
                Layout.fillWidth: true
                visible: mediaTools && mediaTools.downloading
                from: 0
                to: 1
                value: mediaTools ? mediaTools.progress : 0
            }
            Text {
                Layout.fillWidth: true
                visible: mediaTools && mediaTools.status.length > 0
                text: mediaTools ? mediaTools.status : ""
                color: root.cyan
                font.pixelSize: 12
            }
            RowLayout {
                Layout.fillWidth: true
                spacing: 10
                GlowButton {
                    Layout.fillWidth: true
                    text: "Not now"
                    visible: mediaTools && !mediaTools.downloading
                    onClicked: mediaToolsDialog.close()
                }
                GlowButton {
                    Layout.fillWidth: true
                    text: "Install"
                    visible: mediaTools && !mediaTools.downloading
                    onClicked: mediaTools.install()
                }
                GlowButton {
                    Layout.fillWidth: true
                    text: "Cancel download"
                    visible: mediaTools && mediaTools.downloading
                    onClicked: mediaTools.cancel()
                }
            }
        }
    }

    Dialog {
        id: errorDialog
        anchors.centerIn: parent
        width: 480
        modal: true
        title: "ReelFerry"
        standardButtons: Dialog.Ok
        property string message: ""
        background: Rectangle { radius: 18; color: "#F2181D2B"; border.color: "#B65C70" }
        Text { width: parent.width; text: errorDialog.message; color: root.textPrimary; wrapMode: Text.Wrap; font.pixelSize: 14 }
    }

    FileDialog {
        id: fileDialog
        title: "Open media"
        fileMode: FileDialog.OpenFiles
        nameFilters: ["Media files (*.mp4 *.m4v *.mov *.mkv *.avi *.webm *.wmv *.mpg *.mpeg *.vob *.flv *.ogv *.3gp *.mts *.ts *.m2ts *.mp3 *.m4a *.m4b *.aac *.flac *.wav *.ogg *.opus *.wma)", "All files (*)"]
        onAccepted: playback.openFiles(selectedFiles)
    }

    FileDialog {
        id: subtitleDialog
        title: "Choose subtitle file"
        fileMode: FileDialog.OpenFile
        nameFilters: ["Subtitle files (*.srt *.ass *.ssa *.vtt *.sup *.idx)", "All files (*)"]
        onAccepted: playback.selectExternalSubtitle(selectedFile)
    }

    Connections {
        target: playback
        function onErrorOccurred(message) { errorDialog.message = message; errorDialog.open() }
        function onFallbackSuggested(message) { fallbackDialog.message = message; fallbackDialog.open() }
        function onResumeSuggested(title, position) {
            resumeDialog.mediaTitle = title
            resumeDialog.savedPosition = position
            resumeDialog.open()
        }
    }
    Connections {
        target: airplay
        function onErrorOccurred(message) { errorDialog.message = message; errorDialog.open() }
        function onRecoveryNeeded(message) {
            recoveryDialog.message = message
            recoveryDialog.open()
        }
    }
    Connections {
        target: windowsIntegration
        function onErrorOccurred(message) { errorDialog.message = message; errorDialog.open() }
    }
    Connections {
        target: appSettings
        function onErrorOccurred(message) { errorDialog.message = message; errorDialog.open() }
    }
    Connections {
        target: mediaTools
        function onPromptRequested() { mediaToolsDialog.open() }
        function onErrorOccurred(message) {
            errorDialog.message = message
            errorDialog.open()
        }
        function onChanged() {
            if (mediaTools.available && mediaToolsDialog.opened)
                mediaToolsDialog.close()
        }
    }

    Shortcut { sequence: "Ctrl+O"; onActivated: fileDialog.open() }
    Shortcut { sequence: "Ctrl+L"; onActivated: urlDialog.open() }
    Shortcut { sequence: "Space"; onActivated: airplay.casting ? airplay.playPause() : playback.playPause() }
    Shortcut { sequence: "Right"; onActivated: airplay.casting ? airplay.seek(airplay.castPosition + 10) : playback.seek(playback.position + 10000) }
    Shortcut { sequence: "Left"; onActivated: airplay.casting ? airplay.seek(Math.max(0, airplay.castPosition - 10)) : playback.seek(Math.max(0, playback.position - 10000)) }
    Shortcut { sequence: "F11"; onActivated: root.toggleVideoFullscreen() }
    Shortcut { sequence: "Alt+Enter"; onActivated: root.toggleVideoFullscreen() }
    Shortcut { sequence: "Escape"; enabled: root.videoFullscreen; onActivated: root.toggleVideoFullscreen() }
}
