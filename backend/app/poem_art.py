"""Draw the three bounded poem illustrations locally for Canva import."""

from __future__ import annotations

from io import BytesIO

from PIL import Image, ImageDraw, ImageFilter

SCENES = ("rain_window", "paper_boat", "lantern")


def _gradient(top: tuple[int, int, int], bottom: tuple[int, int, int]) -> Image.Image:
    image = Image.new("RGB", (960, 840))
    pixels = image.load()
    for y in range(840):
        weight = y / 839
        color = tuple(round(a * (1 - weight) + b * weight) for a, b in zip(top, bottom, strict=True))
        for x in range(960):
            pixels[x, y] = color
    return image


def _glow(image: Image.Image, x: int, y: int, radius: int, color: tuple[int, int, int]) -> None:
    halo = Image.new("RGBA", image.size)
    draw = ImageDraw.Draw(halo)
    draw.ellipse((x - radius, y - radius, x + radius, y + radius), fill=(*color, 195))
    image.paste(Image.alpha_composite(image.convert("RGBA"), halo.filter(ImageFilter.GaussianBlur(95))).convert("RGB"))


def render_poem_scene(scene: str) -> bytes:
    """Return original, deterministic illustrated art; no network or AI credit needed."""
    if scene not in SCENES:
        raise ValueError("Unknown poem illustration")
    palettes = {
        "rain_window": ((19, 38, 68), (240, 154, 132)),
        "paper_boat": ((27, 42, 80), (110, 134, 162)),
        "lantern": ((20, 29, 59), (73, 60, 108)),
    }
    image = _gradient(*palettes[scene])
    draw = ImageDraw.Draw(image)

    if scene == "rain_window":
        _glow(image, 690, 290, 95, (255, 199, 115))
        draw = ImageDraw.Draw(image)
        draw.ellipse((600, 200, 780, 380), fill=(255, 218, 154))
        draw.polygon([(0, 570), (180, 460), (370, 525), (600, 480), (960, 570),
                      (960, 840), (0, 840)], fill=(57, 88, 113))
        draw.polygon([(0, 650), (260, 555), (570, 650), (790, 565), (960, 620),
                      (960, 840), (0, 840)], fill=(29, 55, 78))
        # A warm window, with rain visible against the morning outside.
        draw.rectangle((90, 80, 870, 715), outline=(238, 204, 177), width=22)
        draw.line((480, 90, 480, 705), fill=(238, 204, 177), width=18)
        draw.line((100, 410, 860, 410), fill=(238, 204, 177), width=18)
        draw.rectangle((48, 705, 915, 742), fill=(227, 190, 159))
        for index in range(25):
            x = 145 + (index * 191) % 680
            y = 125 + (index * 103) % 500
            draw.line((x, y, x - 10, y + 30), fill=(201, 224, 230), width=4)
            draw.ellipse((x - 13, y + 23, x - 7, y + 34), fill=(223, 239, 236))

    elif scene == "paper_boat":
        _glow(image, 780, 175, 85, (241, 205, 134))
        draw = ImageDraw.Draw(image)
        draw.ellipse((718, 116, 842, 240), fill=(255, 225, 164))
        draw.polygon([(0, 470), (220, 445), (455, 490), (710, 415), (960, 460),
                      (960, 840), (0, 840)], fill=(33, 83, 110))
        for index in range(15):
            y = 500 + index * 22
            offset = (index * 83) % 170
            draw.arc((-125 + offset, y, 485 + offset, y + 75), 190, 340,
                     fill=(100 + index * 3, 155 + index * 2, 179 + index), width=3)
            draw.arc((425 - offset, y + 15, 1080 - offset, y + 95), 185, 330,
                     fill=(112, 165, 187), width=3)
        # Folded paper boat floats above its reflection.
        draw.polygon([(305, 456), (655, 456), (592, 551), (376, 551)], fill=(241, 235, 214))
        draw.line((305, 456, 655, 456, 592, 551, 376, 551, 305, 456),
                  fill=(211, 197, 173), width=5, joint="curve")
        draw.polygon([(481, 267), (481, 453), (342, 453)], fill=(255, 249, 226))
        draw.polygon([(490, 288), (627, 453), (490, 453)], fill=(221, 221, 214))
        draw.line((485, 266, 485, 455), fill=(188, 182, 167), width=4)
        draw.arc((286, 539, 670, 685), 10, 167, fill=(228, 209, 159), width=6)

    else:
        _glow(image, 480, 355, 130, (255, 176, 89))
        draw = ImageDraw.Draw(image)
        for index in range(25):
            x = 60 + (index * 163) % 860
            y = 60 + (index * 107) % 580
            draw.ellipse((x, y, x + 3 + index % 4, y + 3 + index % 4),
                         fill=(249, 216, 168))
        draw.polygon([(0, 680), (250, 610), (490, 700), (760, 605), (960, 660),
                      (960, 840), (0, 840)], fill=(34, 43, 75))
        # The lantern is held between two silhouettes, carrying the light forward.
        draw.polygon([(0, 840), (0, 714), (285, 587), (385, 605), (484, 743),
                      (433, 840)], fill=(28, 37, 66))
        draw.polygon([(960, 840), (960, 714), (675, 587), (575, 605), (476, 743),
                      (527, 840)], fill=(28, 37, 66))
        draw.rounded_rectangle((389, 286, 571, 569), radius=35,
                               fill=(196, 113, 69), outline=(255, 206, 134), width=9)
        draw.rounded_rectangle((411, 319, 549, 542), radius=17, fill=(252, 202, 123))
        draw.ellipse((438, 365, 522, 465), fill=(255, 240, 179))
        draw.arc((429, 226, 531, 325), 190, 350, fill=(255, 214, 153), width=12)
        draw.line((392, 573, 568, 573), fill=(247, 187, 118), width=11)

    output = BytesIO()
    image.save(output, format="PNG", optimize=True)
    return output.getvalue()
