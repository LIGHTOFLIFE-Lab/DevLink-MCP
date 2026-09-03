# Copyright 2026 DevLink-MCP contributors
# SPDX-License-Identifier: Apache-2.0
"""Draw the application icon.

Kept as code rather than a checked-in binary so the icon can be regenerated at
any size, and so a change to it is a readable diff. Produces a 1024px PNG;
build_macos.sh turns that into an .icns and build_windows.ps1 into an .ico.

    pip install pillow && python packaging/make_icon.py build/icon.png

Two rounded links, crossing, on a dark plate — the shape says "connection"
without needing a label at 32 pixels.
"""

from __future__ import annotations

import sys
from pathlib import Path

from PIL import Image, ImageDraw

SIZE = 1024
SS = 4  # supersample, then downscale: cheap antialiasing
PLATE = (14, 22, 40, 255)
PLATE_EDGE = (38, 52, 82, 255)
LINK_A = (96, 165, 250, 255)
LINK_B = (52, 211, 153, 255)


def draw(path: Path) -> Path:
    n = SIZE * SS
    img = Image.new("RGBA", (n, n), (0, 0, 0, 0))
    d = ImageDraw.Draw(img)

    # The plate. macOS crops to its own mask, Windows does not, so the corner
    # radius has to look right on its own.
    d.rounded_rectangle([0, 0, n - 1, n - 1], radius=int(n * 0.22),
                        fill=PLATE, outline=PLATE_EDGE, width=int(n * 0.008))

    links = Image.new("RGBA", (n, n), (0, 0, 0, 0))
    ld = ImageDraw.Draw(links)
    stroke = int(n * 0.085)
    radius = int(n * 0.115)
    half, height = int(n * 0.205), int(n * 0.115)
    cx, cy = n // 2, n // 2
    offset = int(n * 0.105)     # how far each link sits from centre

    for dx, colour in ((-offset, LINK_A), (offset, LINK_B)):
        ld.rounded_rectangle(
            [cx + dx - half, cy - height, cx + dx + half, cy + height],
            radius=radius, outline=colour, width=stroke,
        )

    # Rotated so the pair reads as a chain rather than two stacked pills.
    links = links.rotate(-38, resample=Image.BICUBIC, center=(cx, cy))
    img.alpha_composite(links)

    img = img.resize((SIZE, SIZE), Image.LANCZOS)
    path.parent.mkdir(parents=True, exist_ok=True)
    img.save(path)
    return path


if __name__ == "__main__":
    out = Path(sys.argv[1]) if len(sys.argv) > 1 else Path("build/icon.png")
    print(draw(out))
