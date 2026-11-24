"""HTTP API and web UI. Run: uvicorn --factory labelqueue.main:create_app --host 0.0.0.0 --port 8000"""

import asyncio
import re
import urllib.error
import urllib.request
from contextlib import asynccontextmanager
from pathlib import Path
from typing import Literal

from fastapi import FastAPI, HTTPException, Query, Request
from fastapi.responses import FileResponse, JSONResponse, Response
from fastapi.staticfiles import StaticFiles
from PIL import Image, UnidentifiedImageError
from pydantic import BaseModel, Field

from labelqueue import render, tspl
from labelqueue.config import Settings, size_dots
from labelqueue.jobs import Jobs
from labelqueue.transport import make_transport

STATIC = Path(__file__).with_name("static")
MAX_UPLOAD = 15 * 1024 * 1024
CODE_RE = re.compile(r"^[A-Za-z0-9]{1,8}(-[A-Za-z0-9]{1,8}){0,3}$")

Fit = Literal["contain", "cover", "stretch"]
Rotate = Literal["auto", "0", "90", "180", "270"]


class Common(BaseModel):
    size: str | None = None
    copies: int = Field(1, ge=1, le=50)
    source: str = Field("api", max_length=40)


class TextReq(Common):
    lines: list[str] = Field(..., min_length=1, max_length=8)
    qr: str | None = Field(None, max_length=1000)


class ImageUrlReq(Common):
    url: str = Field(..., pattern=r"^https?://")
    fit: Fit = "contain"
    rotate: Rotate = "auto"
    dither: bool = False


class BinsightReq(Common):
    code: str


def create_app(settings: Settings | None = None) -> FastAPI:
    s = settings or Settings.from_env()
    s.data_dir.mkdir(parents=True, exist_ok=True)
    transport = make_transport(s)
    jobs = Jobs(s.data_dir, transport)

    @asynccontextmanager
    async def lifespan(_: FastAPI):
        worker = asyncio.create_task(jobs.run())
        yield
        worker.cancel()
        await transport.close()

    app = FastAPI(title="labelqueue", lifespan=lifespan)
    app.state.jobs, app.state.settings = jobs, s

    def _size(name: str | None, fallback: str) -> str:
        name = name or fallback
        if name not in s.sizes:
            raise HTTPException(422, f"unknown size {name!r}; known: {', '.join(s.sizes)}")
        return name

    def _fetch(url: str) -> bytes:
        try:
            req = urllib.request.Request(url, headers={"User-Agent": "labelqueue"})
            with urllib.request.urlopen(req, timeout=10) as r:
                data = r.read(MAX_UPLOAD + 1)
        except urllib.error.HTTPError as e:
            raise HTTPException(502, f"fetching {url} failed: HTTP {e.code}") from e
        except (urllib.error.URLError, TimeoutError) as e:
            raise HTTPException(502, f"fetching {url} failed: {e}") from e
        if len(data) > MAX_UPLOAD:
            raise HTTPException(413, "image too large")
        return data

    def _decode(data: bytes) -> Image.Image:
        try:
            return render.load_image(data)
        except (UnidentifiedImageError, Image.DecompressionBombError, OSError) as e:
            raise HTTPException(422, f"not a usable image: {e}") from e

    # Each builder returns (size name, 1-bit image, summary for history).
    def build_text(req: TextReq) -> tuple[str, Image.Image, str]:
        size = _size(req.size, s.default_size)
        img = render.text_label(req.lines, size_dots(size), qr=req.qr)
        return size, img, " / ".join(req.lines) + (f" [QR {req.qr}]" if req.qr else "")

    def build_image(data: bytes, size: str | None, fit: str, rotate: str, dither: bool, summary: str, margin: int = render.MARGIN):
        name = _size(size, s.default_size)
        img = render.fit_image(_decode(data), size_dots(name), fit=fit, rotate=rotate, dither=dither, margin=margin)
        return name, img, summary

    async def build_binsight(req: BinsightReq):
        if not s.binsight_url:
            raise HTTPException(404, "Binsight integration not configured (set BINSIGHT_URL)")
        code = req.code.strip().upper()
        if not CODE_RE.match(code):
            raise HTTPException(422, "that doesn't look like a Binsight code (e.g. 183-JHL)")
        url = f"{s.binsight_url}/api/labels/{code}/image"
        try:
            data = await asyncio.to_thread(_fetch, url)
        except HTTPException as e:
            if "HTTP 404" in str(e.detail):
                raise HTTPException(404, f"Binsight has no location {code}") from e
            raise
        return build_image(data, req.size or s.binsight_size, "contain", "auto", False, f"Binsight {code}", margin=0)  # the label is drawn to its own margins

    def enqueue(kind: str, req: Common, built) -> dict:
        size, img, summary = built
        w_mm, h_mm = s.sizes[size]
        payload = tspl.bitmap_job(img, w_mm, h_mm, copies=req.copies, density=s.density, speed=s.speed, gap_mm=s.gap_mm, x=s.x_offset)
        job_id = jobs.add(
            source=req.source, kind=kind, size=size, copies=req.copies, summary=summary,
            preview_png=render.png_bytes(img), payload=payload,
        )
        return {"id": job_id, "status": "queued", "size": size}

    async def respond(job: dict, wait: bool) -> JSONResponse:
        if wait:
            await jobs.wait(job["id"], 30)
            row = jobs.get(job["id"]) or {}
            code = 502 if row.get("status") == "failed" else 200
            return JSONResponse(row, status_code=code)
        return JSONResponse(job, status_code=202)

    def png(img: Image.Image) -> Response:
        return Response(render.png_bytes(img), media_type="image/png")

    async def image_input(request: Request, size, copies, fit, rotate, dither, source, margin=render.MARGIN):
        """Raw image body (Content-Type image/*) with query options, or JSON {"url": ...}."""
        ctype = request.headers.get("content-type", "")
        if ctype.startswith("application/json"):
            req = ImageUrlReq(**await request.json())
            data = await asyncio.to_thread(_fetch, req.url)
            return req, build_image(data, req.size, req.fit, req.rotate, req.dither, req.url)
        body = await request.body()
        if not body:
            raise HTTPException(422, "send an image body or JSON {\"url\": ...}")
        if len(body) > MAX_UPLOAD:
            raise HTTPException(413, "image too large")
        req = Common(size=size, copies=copies, source=source)
        return req, build_image(body, size, fit, rotate, dither, f"image {len(body) // 1024} KB", margin)

    # ---- print ----
    @app.post("/api/print/text")
    async def print_text(req: TextReq, wait: bool = False):
        return await respond(enqueue("text", req, build_text(req)), wait)

    @app.post("/api/print/image")
    async def print_image(
        request: Request, wait: bool = False, size: str | None = None, copies: int = Query(1, ge=1, le=50),
        fit: Fit = "contain", rotate: Rotate = "auto", dither: bool = False, source: str = "api",
        margin: int = Query(render.MARGIN, ge=0, le=100),
    ):
        req, built = await image_input(request, size, copies, fit, rotate, dither, source, margin)
        return await respond(enqueue("image", req, built), wait)

    @app.post("/api/print/binsight")
    async def print_binsight(req: BinsightReq, wait: bool = False):
        return await respond(enqueue("binsight", req, await build_binsight(req)), wait)

    # ---- preview: the exact bitmap that would print ----
    @app.post("/api/preview/text")
    async def preview_text(req: TextReq):
        return png(build_text(req)[1])

    @app.post("/api/preview/image")
    async def preview_image(
        request: Request, size: str | None = None, fit: Fit = "contain", rotate: Rotate = "auto", dither: bool = False,
        margin: int = Query(render.MARGIN, ge=0, le=100),
    ):
        _, built = await image_input(request, size, 1, fit, rotate, dither, "preview", margin)
        return png(built[1])

    @app.post("/api/preview/binsight")
    async def preview_binsight(req: BinsightReq):
        return png((await build_binsight(req))[1])

    # ---- printer control and state ----
    @app.post("/api/selftest")
    async def selftest():
        await transport.send(tspl.selftest())
        return {"ok": True}

    @app.get("/api/status")
    async def status():
        return {
            "transport": transport.kind,
            "address": s.address or None,
            "connected": transport.connected,
            "queue": jobs.queue.qsize(),
            "last_error": jobs.last_error,
            "last_ok": jobs.last_ok,
        }

    @app.get("/api/config")
    async def config():
        return {
            "sizes": {k: {"mm": v, "dots": size_dots(k)} for k, v in s.sizes.items()},
            "default_size": s.default_size,
            "binsight_size": s.binsight_size,
            "binsight": bool(s.binsight_url),
        }

    @app.get("/api/jobs")
    async def list_jobs(limit: int = Query(50, ge=1, le=200)):
        return {"jobs": jobs.recent(limit)}

    @app.get("/api/jobs/{job_id}")
    async def get_job(job_id: int):
        row = jobs.get(job_id)
        if not row:
            raise HTTPException(404, "no such job")
        return row

    @app.get("/api/jobs/{job_id}/preview.png")
    async def job_preview(job_id: int):
        p = jobs.previews / f"{job_id}.png"
        if not p.exists():
            raise HTTPException(404, "no preview")
        return FileResponse(p, media_type="image/png")

    @app.get("/healthz")
    async def healthz():
        return {"ok": True}

    @app.get("/")
    async def index():
        return FileResponse(STATIC / "index.html")

    app.mount("/static", StaticFiles(directory=STATIC), name="static")
    return app
