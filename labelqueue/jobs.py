"""One printer, so one worker: jobs print in order. History lives in a small SQLite file."""

import asyncio
import sqlite3
import time
from dataclasses import dataclass
from pathlib import Path

from labelqueue.transport import Transport

KEEP = 200

SCHEMA = """
create table if not exists jobs (
  id integer primary key,
  created real not null,
  source text not null,
  kind text not null,
  size text not null,
  copies integer not null,
  summary text not null,
  status text not null,
  error text
)
"""


@dataclass
class Job:
    id: int
    payload: bytes
    done: asyncio.Event


class Jobs:
    def __init__(self, data_dir: Path, transport: Transport) -> None:
        self.dir = data_dir
        self.previews = data_dir / "previews"
        self.previews.mkdir(parents=True, exist_ok=True)
        self.db = sqlite3.connect(data_dir / "jobs.db", check_same_thread=False)
        self.db.row_factory = sqlite3.Row
        self.db.execute(SCHEMA)
        # Anything left mid-flight by a restart never printed.
        self.db.execute("update jobs set status='failed', error='server restarted' where status in ('queued','printing')")
        self.db.commit()
        self.transport = transport
        self.queue: asyncio.Queue[Job] = asyncio.Queue()
        self.last_error: str | None = None
        self.last_ok: float | None = None
        self._events: dict[int, asyncio.Event] = {}

    def add(self, *, source: str, kind: str, size: str, copies: int, summary: str, preview_png: bytes, payload: bytes) -> int:
        cur = self.db.execute(
            "insert into jobs (created, source, kind, size, copies, summary, status) values (?,?,?,?,?,?, 'queued')",
            (time.time(), source, kind, size, copies, summary[:200]),
        )
        self.db.commit()
        job_id = int(cur.lastrowid)
        (self.previews / f"{job_id}.png").write_bytes(preview_png)
        done = asyncio.Event()
        self._events[job_id] = done
        self.queue.put_nowait(Job(job_id, payload, done))
        self._prune()
        return job_id

    async def wait(self, job_id: int, timeout: float) -> None:
        ev = self._events.get(job_id)
        if ev:
            try:
                await asyncio.wait_for(ev.wait(), timeout)
            except TimeoutError:
                pass

    def _set(self, job_id: int, status: str, error: str | None = None) -> None:
        self.db.execute("update jobs set status=?, error=? where id=?", (status, error, job_id))
        self.db.commit()

    async def run(self) -> None:
        while True:
            job = await self.queue.get()
            self._set(job.id, "printing")
            try:
                await self.transport.send(job.payload)
            except Exception as e:  # report every printer failure to the caller and the UI
                self.last_error = f"{type(e).__name__}: {e}"
                self._set(job.id, "failed", self.last_error)
            else:
                self.last_error, self.last_ok = None, time.time()
                self._set(job.id, "done")
            job.done.set()
            self._events.pop(job.id, None)

    def get(self, job_id: int) -> dict | None:
        row = self.db.execute("select * from jobs where id=?", (job_id,)).fetchone()
        return dict(row) if row else None

    def recent(self, limit: int = 50) -> list[dict]:
        rows = self.db.execute("select * from jobs order by id desc limit ?", (limit,)).fetchall()
        return [dict(r) for r in rows]

    def _prune(self) -> None:
        old = self.db.execute("select id from jobs order by id desc limit -1 offset ?", (KEEP,)).fetchall()
        for (job_id,) in old:
            (self.previews / f"{job_id}.png").unlink(missing_ok=True)
        if old:
            self.db.execute("delete from jobs where id in (%s)" % ",".join("?" * len(old)), [r[0] for r in old])
            self.db.commit()
