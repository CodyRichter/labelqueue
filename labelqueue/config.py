"""Settings come from the environment (installed: /etc/labelqueue/labelqueue.env)."""

import os
from dataclasses import dataclass, field
from pathlib import Path

DPI = 203  # thermal heads on these printers are 8 dots/mm

# Label stock as (width_mm, height_mm): width runs across the print head.
SIZES: dict[str, tuple[float, float]] = {
    "4x6": (101.6, 152.4),
    "4x3": (101.6, 76.2),
    "3x2": (76.2, 50.8),
    "2x3": (50.8, 76.2),
    "2x1": (50.8, 25.4),
    "2.25x1.25": (57.15, 31.75),
}


def mm_to_dots(mm: float) -> int:
    return round(mm / 25.4 * DPI)


def size_dots(name: str) -> tuple[int, int]:
    w, h = SIZES[name]
    return mm_to_dots(w), mm_to_dots(h)


@dataclass(frozen=True)
class Settings:
    transport: str = "file"  # file | rfcomm | ble
    address: str = ""  # printer Bluetooth MAC
    rfcomm_channel: int = 1
    ble_char: str = ""  # writable GATT characteristic UUID
    ble_chunk: int = 180
    data_dir: Path = Path("./data")
    default_size: str = "4x6"
    binsight_size: str = "2x3"
    binsight_url: str = ""  # Binsight base URL; empty turns the integration off
    density: int = 8  # TSPL DENSITY 0-15
    speed: float | None = None  # TSPL SPEED in inches/s; unset = printer default. Lower = darker solids.
    gap_mm: float = 2.0  # gap between die-cut labels
    x_offset: int = 0  # dots, to nudge the image if the stock sits off-centre
    sizes: dict[str, tuple[float, float]] = field(default_factory=lambda: dict(SIZES))

    @classmethod
    def from_env(cls) -> "Settings":
        e = os.environ.get
        return cls(
            transport=e("LABELQUEUE_TRANSPORT", "file"),
            address=e("LABELQUEUE_ADDRESS", ""),
            rfcomm_channel=int(e("LABELQUEUE_RFCOMM_CHANNEL", "1")),
            ble_char=e("LABELQUEUE_BLE_CHAR", ""),
            ble_chunk=int(e("LABELQUEUE_BLE_CHUNK", "180")),
            data_dir=Path(e("LABELQUEUE_DATA", "./data")),
            default_size=e("LABELQUEUE_DEFAULT_SIZE", "4x6"),
            binsight_size=e("LABELQUEUE_BINSIGHT_SIZE", "2x3"),
            binsight_url=e("BINSIGHT_URL", "").rstrip("/"),
            density=int(e("LABELQUEUE_DENSITY", "8")),
            speed=float(e("LABELQUEUE_SPEED", "0")) or None,
            gap_mm=float(e("LABELQUEUE_GAP_MM", "2")),
            x_offset=int(e("LABELQUEUE_X_OFFSET", "0")),
        )
