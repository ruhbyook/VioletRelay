import QtQuick

Item {
    id: icon

    property string name: ""
    property color color: "white"
    property real strokeWidth: 1.8

    implicitWidth: 18
    implicitHeight: 18

    function roundedRectPath(context, x, y, width, height, radius) {
        context.moveTo(x + radius, y)
        context.lineTo(x + width - radius, y)
        context.quadraticCurveTo(x + width, y, x + width, y + radius)
        context.lineTo(x + width, y + height - radius)
        context.quadraticCurveTo(
            x + width,
            y + height,
            x + width - radius,
            y + height
        )
        context.lineTo(x + radius, y + height)
        context.quadraticCurveTo(x, y + height, x, y + height - radius)
        context.lineTo(x, y + radius)
        context.quadraticCurveTo(x, y, x + radius, y)
    }

    Canvas {
        id: canvas
        anchors.fill: parent
        antialiasing: true

        onPaint: {
            var context = getContext("2d")
            context.setTransform(1, 0, 0, 1, 0, 0)
            context.clearRect(0, 0, width, height)
            context.save()
            context.scale(width / 20, height / 20)
            context.strokeStyle = icon.color
            context.fillStyle = icon.color
            context.lineWidth = icon.strokeWidth
            context.lineCap = "round"
            context.lineJoin = "round"

            switch (icon.name) {
            case "plus":
                context.beginPath()
                context.moveTo(10, 4.5)
                context.lineTo(10, 15.5)
                context.moveTo(4.5, 10)
                context.lineTo(15.5, 10)
                context.stroke()
                break
            case "link":
                context.beginPath()
                context.moveTo(8.2, 12.7)
                context.lineTo(6.9, 14)
                context.bezierCurveTo(5.4, 15.5, 3.1, 15.5, 1.6, 14)
                context.bezierCurveTo(0.1, 12.5, 0.1, 10.2, 1.6, 8.7)
                context.lineTo(4.1, 6.2)
                context.bezierCurveTo(5.6, 4.7, 7.9, 4.7, 9.4, 6.2)
                context.moveTo(11.8, 7.3)
                context.lineTo(13.1, 6)
                context.bezierCurveTo(14.6, 4.5, 16.9, 4.5, 18.4, 6)
                context.bezierCurveTo(19.9, 7.5, 19.9, 9.8, 18.4, 11.3)
                context.lineTo(15.9, 13.8)
                context.bezierCurveTo(14.4, 15.3, 12.1, 15.3, 10.6, 13.8)
                context.moveTo(6.9, 13.1)
                context.lineTo(13.1, 6.9)
                context.stroke()
                break
            case "cast":
                context.beginPath()
                icon.roundedRectPath(context, 3.5, 3, 13, 10.5, 1.5)
                context.stroke()
                context.beginPath()
                context.moveTo(6.5, 17)
                context.lineTo(13.5, 17)
                context.lineTo(10, 13)
                context.closePath()
                context.fill()
                break
            case "captions":
                context.beginPath()
                context.arc(6.5, 10, 3.1, 0.72, Math.PI * 2 - 0.72)
                context.stroke()
                context.beginPath()
                context.arc(13.5, 10, 3.1, 0.72, Math.PI * 2 - 0.72)
                context.stroke()
                break
            case "grid":
                context.beginPath()
                icon.roundedRectPath(context, 3.5, 3.5, 5, 5, 1)
                icon.roundedRectPath(context, 11.5, 3.5, 5, 5, 1)
                icon.roundedRectPath(context, 3.5, 11.5, 5, 5, 1)
                icon.roundedRectPath(context, 11.5, 11.5, 5, 5, 1)
                context.stroke()
                break
            case "heart":
                context.beginPath()
                context.moveTo(10, 16.6)
                context.bezierCurveTo(8.8, 15.4, 3.7, 12, 3.7, 7.7)
                context.bezierCurveTo(3.7, 5.1, 5.5, 3.4, 7.8, 3.4)
                context.bezierCurveTo(9.1, 3.4, 10, 4.1, 10, 4.1)
                context.bezierCurveTo(10, 4.1, 10.9, 3.4, 12.2, 3.4)
                context.bezierCurveTo(14.5, 3.4, 16.3, 5.1, 16.3, 7.7)
                context.bezierCurveTo(16.3, 12, 11.2, 15.4, 10, 16.6)
                context.closePath()
                context.stroke()
                break
            case "info":
                context.beginPath()
                context.arc(10, 10, 7, 0, Math.PI * 2)
                context.stroke()
                context.beginPath()
                context.arc(10, 6.3, 1, 0, Math.PI * 2)
                context.fill()
                context.beginPath()
                context.moveTo(10, 9.2)
                context.lineTo(10, 14)
                context.stroke()
                break
            case "previous":
                context.fillRect(4.6, 5, 1.8, 10)
                context.beginPath()
                context.moveTo(14.3, 5)
                context.lineTo(6.8, 10)
                context.lineTo(14.3, 15)
                context.closePath()
                context.fill()
                break
            case "next":
                context.fillRect(13.6, 5, 1.8, 10)
                context.beginPath()
                context.moveTo(5.7, 5)
                context.lineTo(13.2, 10)
                context.lineTo(5.7, 15)
                context.closePath()
                context.fill()
                break
            case "play":
                context.beginPath()
                context.moveTo(7, 5)
                context.lineTo(16, 10)
                context.lineTo(7, 15)
                context.closePath()
                context.fill()
                break
            case "pause":
                context.beginPath()
                icon.roundedRectPath(context, 5.8, 4.5, 3.1, 11, 1)
                icon.roundedRectPath(context, 11.1, 4.5, 3.1, 11, 1)
                context.fill()
                break
            case "volume":
            case "muted":
                context.beginPath()
                context.moveTo(3.5, 8)
                context.lineTo(7, 8)
                context.lineTo(10.5, 5)
                context.lineTo(10.5, 15)
                context.lineTo(7, 12)
                context.lineTo(3.5, 12)
                context.closePath()
                context.fill()
                if (icon.name === "volume") {
                    context.beginPath()
                    context.arc(10.5, 10, 3.2, -0.85, 0.85)
                    context.stroke()
                    context.beginPath()
                    context.arc(10.5, 10, 5.5, -0.72, 0.72)
                    context.stroke()
                } else {
                    context.beginPath()
                    context.moveTo(12.5, 7.2)
                    context.lineTo(17, 12.8)
                    context.moveTo(17, 7.2)
                    context.lineTo(12.5, 12.8)
                    context.stroke()
                }
                break
            case "fullscreen":
                context.beginPath()
                context.moveTo(8, 4)
                context.lineTo(4, 4)
                context.lineTo(4, 8)
                context.moveTo(12, 4)
                context.lineTo(16, 4)
                context.lineTo(16, 8)
                context.moveTo(4, 12)
                context.lineTo(4, 16)
                context.lineTo(8, 16)
                context.moveTo(16, 12)
                context.lineTo(16, 16)
                context.lineTo(12, 16)
                context.stroke()
                break
            case "exit-fullscreen":
                context.beginPath()
                context.moveTo(8, 3.5)
                context.lineTo(8, 8)
                context.lineTo(3.5, 8)
                context.moveTo(12, 3.5)
                context.lineTo(12, 8)
                context.lineTo(16.5, 8)
                context.moveTo(3.5, 12)
                context.lineTo(8, 12)
                context.lineTo(8, 16.5)
                context.moveTo(16.5, 12)
                context.lineTo(12, 12)
                context.lineTo(12, 16.5)
                context.stroke()
                break
            }
            context.restore()
        }

        onWidthChanged: requestPaint()
        onHeightChanged: requestPaint()
    }

    onNameChanged: canvas.requestPaint()
    onColorChanged: canvas.requestPaint()
    onStrokeWidthChanged: canvas.requestPaint()
}
