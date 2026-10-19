"""Shared visual tokens for the Sofia Desktop experience."""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class DesktopPalette:
    background: str = "#06131a"
    surface: str = "#081820"
    surface_raised: str = "#10242d"
    surface_user: str = "#0b3450"
    border: str = "#123440"
    border_strong: str = "#145164"
    accent: str = "#22d7f2"
    accent_soft: str = "#7fddea"
    text_primary: str = "#eef9fc"
    text_secondary: str = "#8db2be"
    success: str = "#2cf2c5"
    warning: str = "#f2b84b"
    danger: str = "#f06a6a"


PALETTE = DesktopPalette()

RADIUS_SM = 7
RADIUS_MD = 10
RADIUS_LG = 14

SPACE_XS = 4
SPACE_SM = 8
SPACE_MD = 12
SPACE_LG = 16
SPACE_XL = 24


def desktop_icon(name: str, size: int = 22, color: str = "#22d7f2"):
    """Render monochrome, antialiased UI icons without emoji or font dependencies."""
    from PySide6.QtCore import Qt, QRectF, QLineF
    from PySide6.QtGui import QColor, QIcon, QPainter, QPainterPath, QPen, QPixmap

    pixmap = QPixmap(size, size)
    pixmap.fill(Qt.GlobalColor.transparent)
    painter = QPainter(pixmap)
    painter.setRenderHint(QPainter.RenderHint.Antialiasing)
    painter.scale(size / 24, size / 24)
    pen = QPen(QColor(color), 1.9, Qt.PenStyle.SolidLine,
               Qt.PenCapStyle.RoundCap, Qt.PenJoinStyle.RoundJoin)
    painter.setPen(pen)
    painter.setBrush(Qt.BrushStyle.NoBrush)

    if name == "mic":
        painter.drawRoundedRect(QRectF(9, 3, 6, 12), 3, 3)
        path = QPainterPath()
        path.moveTo(5.5, 11)
        path.cubicTo(5.5, 20, 18.5, 20, 18.5, 11)
        painter.drawPath(path)
        painter.drawLine(QLineF(12, 19, 12, 22))
        painter.drawLine(QLineF(9, 22, 15, 22))
    elif name == "send":
        path = QPainterPath()
        path.moveTo(3, 4)
        path.lineTo(21, 12)
        path.lineTo(3, 20)
        path.lineTo(7, 12)
        path.closeSubpath()
        painter.drawPath(path)
        painter.drawLine(QLineF(7, 12, 21, 12))
    elif name == "chat":
        painter.drawRoundedRect(QRectF(3, 4, 18, 14), 4, 4)
        painter.drawLine(QLineF(7, 18, 6, 21))
        painter.drawLine(QLineF(6, 21, 12, 18))
    elif name == "tasks":
        painter.drawRoundedRect(QRectF(4, 3, 16, 18), 3, 3)
        for y in (9, 15):
            painter.drawLine(QLineF(7, y, 9, y + 2))
            painter.drawLine(QLineF(9, y + 2, 12, y - 2))
            painter.drawLine(QLineF(14, y, 18, y))
    elif name == "settings":
        painter.drawEllipse(QRectF(4, 4, 16, 16))
        painter.drawEllipse(QRectF(9, 9, 6, 6))
        for x1, y1, x2, y2 in ((12, 1, 12, 4), (12, 20, 12, 23),
                                (1, 12, 4, 12), (20, 12, 23, 12),
                                (4, 4, 6, 6), (18, 18, 20, 20),
                                (4, 20, 6, 18), (18, 6, 20, 4)):
            painter.drawLine(QLineF(x1, y1, x2, y2))
    elif name == "cloud":
        path = QPainterPath()
        path.moveTo(6, 19)
        path.cubicTo(-1, 19, 2, 10, 7, 10)
        path.cubicTo(7, 2, 18, 2, 19, 11)
        path.cubicTo(24, 12, 23, 19, 18, 19)
        path.closeSubpath()
        painter.drawPath(path)
    else:
        painter.end()
        raise ValueError(f"Unknown desktop icon: {name}")
    painter.end()
    return QIcon(pixmap)
