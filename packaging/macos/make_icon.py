"""Render the project's bubble mark as a macOS app icon."""

import subprocess
import tempfile
from pathlib import Path

from PIL import Image, ImageDraw


OUTPUT = Path(__file__).with_name("AgentMarquee.icns")


def render(size):
    image = Image.new("RGBA", (1024, 1024), (0, 0, 0, 0))
    draw = ImageDraw.Draw(image)
    draw.rounded_rectangle((52, 52, 972, 972), radius=225, fill="#111D33")
    stroke = 64
    draw.line((145, 475, 300, 475), fill="#61DDFF", width=stroke)
    draw.line((190, 355, 300, 355), fill="#61DDFF", width=stroke)
    draw.rounded_rectangle((292, 265, 873, 750), radius=170,
                           outline="#61DDFF", width=stroke)
    for x in (440, 575, 710):
        draw.ellipse((x - 42, 455 - 42, x + 42, 455 + 42), fill="#61DDFF")
    return image.resize((size, size), Image.Resampling.LANCZOS)


def main():
    with tempfile.TemporaryDirectory(prefix="agentmarquee-icon-") as temporary:
        iconset = Path(temporary) / "AgentMarquee.iconset"
        iconset.mkdir()
        for points in (16, 32, 128, 256, 512):
            render(points).save(iconset / f"icon_{points}x{points}.png")
            render(points * 2).save(iconset / f"icon_{points}x{points}@2x.png")
        subprocess.run(["iconutil", "-c", "icns", str(iconset), "-o", str(OUTPUT)], check=True)
    print(OUTPUT)


if __name__ == "__main__":
    main()
