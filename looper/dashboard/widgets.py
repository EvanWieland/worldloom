"""Custom widgets: gradient braille line graph (btop-style) and gradient bars."""
from __future__ import annotations

from rich.text import Text
from textual.widget import Widget

# Gradients: list of (r, g, b) stops, interpolated by value fraction.
TEAL_VIOLET_MAGENTA = [(45, 212, 191), (139, 92, 246), (236, 72, 153)]
BLUE_AMBER_RED = [(59, 130, 246), (245, 158, 11), (239, 68, 68)]
GREEN_AMBER_RED = [(34, 197, 94), (245, 158, 11), (239, 68, 68)]
BRAILLE_BASE = 0x2800
_DOTS = [(0x40, 0x80), (0x04, 0x20), (0x02, 0x10), (0x01, 0x08)]  # dot rows bottom->top, (left, right)


def lerp_color(stops, frac: float) -> str:
    frac = min(max(frac, 0.0), 1.0) * (len(stops) - 1)
    i = min(int(frac), len(stops) - 2)
    t = frac - i
    r, g, b = (round(stops[i][k] + (stops[i + 1][k] - stops[i][k]) * t) for k in range(3))
    return f"#{r:02x}{g:02x}{b:02x}"


def gradient_bar(frac: float, width: int, stops) -> Text:
    filled = round(min(max(frac, 0.0), 1.0) * width)
    t = Text()
    for i in range(width):
        if i < filled:
            t.append("█", style=lerp_color(stops, i / max(width - 1, 1)))
        else:
            t.append("░", style="grey23")
    return t


class BrailleGraph(Widget):
    """Filled line graph drawn in braille dots (2x4 per cell); each column coloured by its value."""

    DEFAULT_CSS = "BrailleGraph { height: 4; }"

    def __init__(self, label: str, gradient, unit: str, vmax: float, **kw):
        super().__init__(**kw)
        self.label, self.gradient, self.unit, self.vmax = label, gradient, unit, vmax
        self._values: list[float | None] = []
        self._latest = ""

    def set_series(self, values: list[float | None], latest_text: str) -> None:
        self._values, self._latest = values, latest_text
        self.refresh()

    def render(self) -> Text:
        w, h = max(self.size.width - 1, 4), max(self.size.height - 1, 1)
        cols = w * 2
        vals = self._values[-cols:]
        vals = [None] * (cols - len(vals)) + vals
        rows = h * 4
        grid = [[0] * w for _ in range(h)]
        colors: list[str | None] = [None] * w
        for x, v in enumerate(vals):
            if v is None:
                continue
            frac = min(max(v / self.vmax, 0.0), 1.0) if self.vmax else 0.0
            level = round(frac * (rows - 1))
            for y in range(level + 1):  # filled area under the line
                grid[h - 1 - y // 4][x // 2] |= _DOTS[y % 4][x % 2]
            colors[x // 2] = lerp_color(self.gradient, frac)
        t = Text()
        t.append(f"{self.label:5}", style="bold #cbd5e1")
        t.append(f" {self._latest}\n", style="#e5e7eb")
        for r in range(h):
            for c in range(w):
                t.append(chr(BRAILLE_BASE + grid[r][c]), style=colors[c] or "grey15")
            if r < h - 1:
                t.append("\n")
        return t
