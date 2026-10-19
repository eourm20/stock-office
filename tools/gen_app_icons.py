"""Generate the Stock Office app icons (home-screen / PWA). Own work, CC0-1.0.

    uv run --no-project --with pillow python tools/gen_app_icons.py
"""

from __future__ import annotations

from pathlib import Path

from PIL import Image, ImageDraw

OUT = Path(__file__).resolve().parents[1] / "frontend" / "public" / "icons"
BG = (11, 16, 32)
PANEL = (20, 29, 50)
MINT = (92, 221, 179)
ROSE = (232, 96, 110)
GOLD = (255, 217, 138)


def draw(size: int, padding: float) -> Image.Image:
    """A pixel-art office tower with a rising chart, drawn on a 32-unit grid."""
    img = Image.new("RGB", (size, size), BG)
    d = ImageDraw.Draw(img)
    inner = size * (1 - 2 * padding)
    u = inner / 32
    ox = oy = size * padding

    def px(x: float, y: float, w: float, h: float, color: tuple[int, int, int]) -> None:
        d.rectangle([ox + x * u, oy + y * u, ox + (x + w) * u - 1, oy + (y + h) * u - 1], fill=color)

    px(2, 2, 28, 28, PANEL)
    # building with lit windows
    px(6, 10, 10, 18, (52, 64, 98))
    for row in range(5):
        for col in range(2):
            px(8 + col * 4, 12 + row * 3, 2, 2, GOLD if (row + col) % 3 else (90, 110, 150))
    # rising chart: bars and an arrow
    for i, (h, c) in enumerate([(5, ROSE), (8, MINT), (11, MINT), (15, MINT)]):
        px(18 + i * 3, 28 - h, 2, h, c)
    for i in range(5):
        px(17 + i * 2.5, 13 - i * 2, 2, 2, GOLD)
    px(27, 4, 3, 2, GOLD)
    px(28, 4, 2, 3, GOLD)
    px(2, 28, 28, 2, (43, 57, 82))
    return img


def main() -> None:
    OUT.mkdir(parents=True, exist_ok=True)
    draw(180, 0.0).save(OUT / "apple-touch-icon.png")        # iOS rounds the corners itself
    draw(192, 0.0).save(OUT / "icon-192.png")
    draw(512, 0.0).save(OUT / "icon-512.png")
    draw(512, 0.12).save(OUT / "icon-maskable-512.png")      # safe zone for masked launchers
    # Browsers request /favicon.ico on their own; serve it instead of a 404.
    draw(64, 0.0).save(OUT.parent / "favicon.ico", sizes=[(16, 16), (32, 32), (48, 48), (64, 64)])
    print("generated:", sorted(p.name for p in OUT.iterdir()))


if __name__ == "__main__":
    main()
