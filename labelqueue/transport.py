"""How job bytes reach the printer. Pick one with LABELQUEUE_TRANSPORT."""

import asyncio
import socket
import time
from pathlib import Path

from labelqueue.config import Settings

IDLE_SECONDS = 60  # keep the link up between jobs in a batch, then let the printer sleep


class Transport:
    kind = "base"

    def __init__(self) -> None:
        self.connected = False

    async def send(self, data: bytes) -> None:
        raise NotImplementedError

    async def close(self) -> None:
        self.connected = False


class FileTransport(Transport):
    """No printer: write each job to data/out/ so everything above the radio can be tested."""

    kind = "file"

    def __init__(self, out_dir: Path) -> None:
        super().__init__()
        self.out_dir = out_dir
        out_dir.mkdir(parents=True, exist_ok=True)

    async def send(self, data: bytes) -> None:
        (self.out_dir / f"{time.time_ns()}.tspl").write_bytes(data)


class RfcommTransport(Transport):
    """Classic Bluetooth serial (SPP). Linux only (AF_BLUETOOTH)."""

    kind = "rfcomm"

    def __init__(self, address: str, channel: int) -> None:
        super().__init__()
        self.address, self.channel = address, channel
        self.sock: socket.socket | None = None
        self._idle: asyncio.TimerHandle | None = None

    def _connect(self) -> socket.socket:
        s = socket.socket(socket.AF_BLUETOOTH, socket.SOCK_STREAM, socket.BTPROTO_RFCOMM)  # type: ignore[attr-defined]
        s.settimeout(15)
        s.connect((self.address, self.channel))
        return s

    def _send_blocking(self, data: bytes) -> None:
        if self.sock is None:
            self.sock = self._connect()
        self.sock.sendall(data)

    async def send(self, data: bytes) -> None:
        try:
            await asyncio.to_thread(self._send_blocking, data)
        except OSError:
            await self.close()  # stale link: reconnect once
            await asyncio.to_thread(self._send_blocking, data)
        self.connected = True
        self._arm_idle()

    def _arm_idle(self) -> None:
        if self._idle:
            self._idle.cancel()
        loop = asyncio.get_running_loop()
        self._idle = loop.call_later(IDLE_SECONDS, lambda: asyncio.ensure_future(self.close()))

    async def close(self) -> None:
        if self.sock is not None:
            try:
                self.sock.close()
            except OSError:
                pass
        self.sock = None
        self.connected = False


class BleTransport(Transport):
    """Bluetooth LE: write the job in chunks to one GATT characteristic."""

    kind = "ble"

    def __init__(self, address: str, char_uuid: str, chunk: int) -> None:
        super().__init__()
        self.address, self.char_uuid, self.chunk = address, char_uuid, chunk
        self.client = None
        self._idle: asyncio.TimerHandle | None = None

    async def _ensure(self):
        from bleak import BleakClient  # only needed on the VM, and only for BLE printers

        if self.client is None or not self.client.is_connected:
            self.client = BleakClient(self.address, timeout=20)
            await self.client.connect()
        return self.client

    async def _write(self, data: bytes) -> None:
        client = await self._ensure()
        for i in range(0, len(data), self.chunk):
            await client.write_gatt_char(self.char_uuid, data[i : i + self.chunk], response=False)
            await asyncio.sleep(0.01)  # cheap printers drop bytes if flooded

    async def send(self, data: bytes) -> None:
        try:
            await self._write(data)
        except Exception:
            await self.close()
            await self._write(data)
        self.connected = True
        if self._idle:
            self._idle.cancel()
        self._idle = asyncio.get_running_loop().call_later(
            IDLE_SECONDS, lambda: asyncio.ensure_future(self.close())
        )

    async def close(self) -> None:
        if self.client is not None:
            try:
                await self.client.disconnect()
            except Exception:
                pass
        self.client = None
        self.connected = False


def make_transport(s: Settings) -> Transport:
    if s.transport == "rfcomm":
        return RfcommTransport(s.address, s.rfcomm_channel)
    if s.transport == "ble":
        return BleTransport(s.address, s.ble_char, s.ble_chunk)
    return FileTransport(s.data_dir / "out")
