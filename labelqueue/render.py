"""Turn images and text into the exact 1-bit bitmap the printer will burn."""

from io import BytesIO
from pathlib import Path

import segno
from PIL import Image, ImageDraw, ImageFont, ImageOps

FONT_CANDIDATES = [
    "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf",
    "/System/Library/Fonts/Supplemental/Arial Bold.ttf",
    "/Library/Fonts/Arial Bold.ttf",
]
MARGIN = 16  # dots (~2 mm) kept clear on every side for feed drift
MAX_PIXELS = 40_000_000  # refuse decompression bombs early


def _font(size: int) -> ImageFont.FreeTypeFont | ImageFont.ImageFont:
    for p in FONT_CANDIDATES:
        if Path(p).exists():
            return ImageFont.truetype(p, size)
    return ImageFont.load_default(size)


def load_image(data: bytes) -> Image.Image:
    Image.MAX_IMAGE_PIXELS = MAX_PIXELS
    img = Image.open(BytesIO(data))
    img.load()
    img = ImageOps.exif_transpose(img)
    if img.mode in ("RGBA", "LA", "P"):
        img = img.convert("RGBA")
        bg = Image.new("RGBA", img.size, (255, 255, 255, 255))
        img = Image.alpha_composite(bg, img)
    return img.convert("L")


def to_1bit(img: Image.Image, dither: bool) -> Image.Image:
    img = img.convert("L")
    if dither:
        return img.convert("1", dither=Image.Dither.FLOYDSTEINBERG)
    return img.point(lambda v: 255 if v >= 128 else 0).convert("1", dither=Image.Dither.NONE)


def fit_image(
    img: Image.Image,
    label: tuple[int, int],
    fit: str = "contain",
    rotate: str = "auto",
    dither: bool = False,
    margin: int = MARGIN,
) -> Image.Image:
    """Place `img` on a white label canvas of `label` dots."""
    lw, lh = label
    img = img.convert("L")
    if rotate == "auto":
        if (img.width > img.height) != (lw > lh) and img.width != img.height:
            img = img.rotate(90, expand=True)
    elif rotate in ("90", "180", "270"):
        img = img.rotate(-int(rotate), expand=True)  # clockwise, like a phone
    bw, bh = lw - 2 * margin, lh - 2 * margin
    if fit == "stretch":
        placed = img.resize((bw, bh), Image.Resampling.LANCZOS)
    elif fit == "cover":
        placed = ImageOps.fit(img, (bw, bh), Image.Resampling.LANCZOS)
    else:
        placed = ImageOps.contain(img, (bw, bh), Image.Resampling.LANCZOS)
    canvas = Image.new("L", (lw, lh), 255)
    canvas.paste(placed, ((lw - placed.width) // 2, (lh - placed.height) // 2))
    return to_1bit(canvas, dither)


def _qr_image(data: str, side: int) -> Image.Image:
    qr = segno.make(data, error="m")
    modules = qr.symbol_size(border=0)[0]
    scale = max(1, side // modules)  # whole dots per module keeps it scannable
    buf = BytesIO()
    qr.save(buf, kind="png", scale=scale, border=0)
    buf.seek(0)
    return Image.open(buf).convert("L")


def _fit_lines(draw: ImageDraw.ImageDraw, lines: list[str], box: tuple[int, int]) -> list:
    """Largest font where every line fits; the first line is the title, drawn 1.5x the rest."""
    bw, bh = box
    lo, hi, best = 8, 400, None
    while lo <= hi:
        mid = (lo + hi) // 2
        fonts = [_font(round(mid * 1.5))] + [_font(mid)] * (len(lines) - 1)
        sizes = [draw.textbbox((0, 0), t or " ", font=f) for t, f in zip(lines, fonts, strict=True)]
        widths = [b[2] - b[0] for b in sizes]
        heights = [f.size * 1.15 for f in fonts]
        if max(widths) <= bw and sum(heights) <= bh:
            best = (fonts, heights)
            lo = mid + 1
        else:
            hi = mid - 1
    if best is None:
        fonts = [_font(8)] * len(lines)
        best = (fonts, [9.2] * len(lines))
    return list(zip(lines, *best, strict=True))


def text_label(
    lines: list[str],
    label: tuple[int, int],
    qr: str | None = None,
    margin: int = MARGIN,
) -> Image.Image:
    lw, lh = label
    canvas = Image.new("L", (lw, lh), 255)
    draw = ImageDraw.Draw(canvas)
    x0, y0, x1, y1 = margin, margin, lw - margin, lh - margin
    if qr:
        landscape = (x1 - x0) >= (y1 - y0)
        side = min(y1 - y0, (x1 - x0) // 2) if landscape else min(x1 - x0, (y1 - y0) // 2)
        code = _qr_image(qr, side)
        if landscape:
            canvas.paste(code, (x0, y0 + (y1 - y0 - code.height) // 2))
            x0 += code.width + margin
        else:
            canvas.paste(code, (x0 + (x1 - x0 - code.width) // 2, y0))
            y0 += code.height + margin
    lines = [ln for ln in lines if ln is not None] or [""]
    if any(lines) and x1 > x0 and y1 > y0:
        laid = _fit_lines(draw, lines, (x1 - x0, y1 - y0))
        total = sum(h for _, _, h in laid)
        y = y0 + (y1 - y0 - total) / 2
        for text, font, h in laid:
            w = draw.textlength(text, font=font)
            draw.text((x0 + (x1 - x0 - w) / 2, y), text, font=font, fill=0)
            y += h
    return to_1bit(canvas, dither=False)


def png_bytes(img: Image.Image) -> bytes:
    buf = BytesIO()
    img.save(buf, format="PNG")
    return buf.getvalue()
