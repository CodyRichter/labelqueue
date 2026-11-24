"""TSPL, the command language of most cheap 4x6 thermal printers (JADENS, iDPRT, Munbyn...).

A job is one full-label 1-bit bitmap: SIZE, GAP, SPEED, DENSITY, CLS, BITMAP, PRINT.
Slower SPEED gives the head more time per line, so large solid blacks come out fully dark.
In TSPL bitmaps a 1 bit is *not* printed (white), which is exactly how Pillow packs
mode "1" images, so the raster goes through unchanged.
"""

from PIL import Image


def _pad_to_byte(img: Image.Image) -> Image.Image:
    """Make the width a multiple of 8, padding with white (Pillow would pad with black bits)."""
    w, h = img.size
    pad = -w % 8
    if not pad:
        return img
    out = Image.new("1", (w + pad, h), 1)
    out.paste(img, (0, 0))
    return out


def bitmap_job(
    img: Image.Image,
    width_mm: float,
    height_mm: float,
    copies: int = 1,
    density: int = 8,
    speed: float | None = None,
    gap_mm: float = 2.0,
    x: int = 0,
    y: int = 0,
) -> bytes:
    if img.mode != "1":
        raise ValueError("bitmap_job needs a 1-bit image")
    img = _pad_to_byte(img)
    width_bytes = img.size[0] // 8
    height = img.size[1]
    head = (
        f"SIZE {width_mm:g} mm,{height_mm:g} mm\r\n"
        f"GAP {gap_mm:g} mm,0 mm\r\n"
        "DIRECTION 1\r\n"
        + (f"SPEED {speed:g}\r\n" if speed else "")
        + f"DENSITY {density}\r\n"
        + "CLS\r\n"
        + f"BITMAP {x},{y},{width_bytes},{height},0,"
    ).encode("ascii")
    return head + img.tobytes() + f"\r\nPRINT 1,{copies}\r\n".encode("ascii")


def selftest() -> bytes:
    return b"SELFTEST\r\n"
