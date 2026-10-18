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
