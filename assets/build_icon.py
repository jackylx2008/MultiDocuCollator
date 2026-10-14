"""Render the editable SVG into the application PNG and Windows ICO.

Requires CairoSVG and Pillow: ``python -m pip install cairosvg pillow``.
"""

from pathlib import Path

import cairosvg
from PIL import Image


HERE = Path(__file__).resolve().parent
PNG = HERE / "serve_summary_icon.png"


def main() -> None:
    cairosvg.svg2png(
        url=str(HERE / "serve_summary_icon.svg"),
        write_to=str(PNG),
        output_width=1024,
        output_height=1024,
    )
    with Image.open(PNG) as icon:
        icon.save(
            HERE / "serve_summary.ico",
            format="ICO",
            sizes=[(16, 16), (24, 24), (32, 32), (48, 48), (64, 64), (128, 128), (256, 256)],
        )


if __name__ == "__main__":
    main()
