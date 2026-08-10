from __future__ import annotations

import argparse
from pathlib import Path

from PIL import Image, ImageDraw


def make_icon(output: Path) -> None:
    size = 1024
    image = Image.new("RGBA", (size, size), "#020509")
    draw = ImageDraw.Draw(image)
    draw.rounded_rectangle((32, 32, 992, 992), radius=190, fill="#07131f", outline="#30d9ff", width=34)

    points = []
    anchors = [(110, 380), (210, 380), (280, 205), (355, 560), (445, 300), (540, 450), (630, 450), (720, 170), (840, 380), (914, 380)]
    for index in range(len(anchors) - 1):
        x0, y0 = anchors[index]; x1, y1 = anchors[index + 1]
        for step in range(20):
            t = step / 20; points.append((x0 + (x1 - x0) * t, y0 + (y1 - y0) * t))
    points.append(anchors[-1])
    draw.line(points, fill="white", width=42, joint="curve")

    bars = [(165, 680, 75), (285, 610, 145), (405, 720, 35), (525, 545, 210), (645, 640, 115), (765, 735, 20)]
    for x, top, _ in bars:
        draw.rounded_rectangle((x, top, x + 66, 855), radius=18, fill="#ffb300")

    output.parent.mkdir(parents=True, exist_ok=True)
    image.save(output, format="ICO", sizes=[(16, 16), (24, 24), (32, 32), (48, 48), (64, 64), (128, 128), (256, 256)])
    image.resize((256, 256), Image.Resampling.LANCZOS).save(output.with_suffix(".png"))


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--output", type=Path, default=Path("build/app.ico"))
    make_icon(parser.parse_args().output)
