import time
from io import BytesIO

import pytest
from fastapi.testclient import TestClient
from PIL import Image

from labelqueue import render, tspl
from labelqueue.config import Settings, size_dots


# ---- tspl ----
def test_bitmap_job_layout():
    img = Image.new("1", (8, 2), 1)
    img.putpixel((0, 0), 0)  # one black dot top-left
    job = tspl.bitmap_job(img, 50.8, 25.4, copies=3, density=10, gap_mm=2)
    head, _, rest = job.partition(b"BITMAP 0,0,1,2,0,")
    assert b"SIZE 50.8 mm,25.4 mm\r\n" in head
    assert b"GAP 2 mm,0 mm\r\n" in head and b"DENSITY 10\r\n" in head and b"SPEED" not in head and b"CLS\r\n" in head
    # 1 bit = white in TSPL: first row 0b01111111, second all white
    assert rest[:2] == bytes([0x7F, 0xFF])
    assert rest[2:] == b"\r\nPRINT 1,3\r\n"


def test_bitmap_pads_width_with_white():
    img = Image.new("1", (10, 1), 0)  # all black, 10 wide -> 2 bytes
    job = tspl.bitmap_job(img, 10, 10)
    data = job.split(b"BITMAP 0,0,2,1,0,")[1][:2]
    assert data == bytes([0x00, 0x3F])  # 10 black dots, then 6 white padding bits


def test_bitmap_rejects_grey():
    with pytest.raises(ValueError):
        tspl.bitmap_job(Image.new("L", (8, 8)), 1, 1)


# ---- render ----
def test_sizes_at_203_dpi():
    assert size_dots("4x6") == (812, 1218)
    assert size_dots("2x1") == (406, 203)


def test_fit_image_contains_and_rotates():
    wide = Image.new("L", (900, 600), 0)  # landscape, black
    out = render.fit_image(wide, size_dots("2x3"))  # portrait label -> auto-rotate
    assert out.mode == "1" and out.size == (406, 609)
    # rotated to portrait, so it fills the width, minus margins
    assert out.getpixel((203, 304)) == 0
    assert out.getpixel((2, 2)) == 255


def test_text_label_has_ink_and_qr():
    out = render.text_label(["Leftovers", "Curry", "Nov 22"], size_dots("3x2"), qr="https://example.com")
    assert out.size == size_dots("3x2")
    hist = out.convert("L").histogram()
    assert hist[0] > 1000 and hist[255] > 1000


def test_load_image_flattens_alpha_to_white():
    rgba = Image.new("RGBA", (10, 10), (0, 0, 0, 0))
    buf = BytesIO()
    rgba.save(buf, "PNG")
    assert render.load_image(buf.getvalue()).getpixel((5, 5)) == 255


# ---- API (FileTransport) ----
@pytest.fixture
def client(tmp_path):
    from labelqueue.main import create_app

    app = create_app(Settings(data_dir=tmp_path, default_size="2x1"))
    with TestClient(app) as c:
        c.out = tmp_path / "out"
        yield c


def _png(w=300, h=200):
    buf = BytesIO()
    Image.new("L", (w, h), 0).save(buf, "PNG")
    return buf.getvalue()


def _wait_out(c, n=1):
    for _ in range(50):
        files = sorted(c.out.glob("*.tspl"))
        if len(files) >= n:
            return files
        time.sleep(0.05)
    raise AssertionError("no job written")


def test_print_text_writes_tspl_and_history(client):
    r = client.post("/api/print/text", json={"lines": ["Hello"], "source": "pytest"})
    assert r.status_code == 202 and r.json()["size"] == "2x1"
    job = _wait_out(client)[0].read_bytes()
    assert job.startswith(b"SIZE 50.8 mm,25.4 mm") and b"BITMAP 0,0,51,203,0," in job
    jobs = client.get("/api/jobs").json()["jobs"]
    assert jobs[0]["source"] == "pytest" and jobs[0]["summary"] == "Hello"
    assert client.get(f"/api/jobs/{jobs[0]['id']}/preview.png").headers["content-type"] == "image/png"


def test_print_wait_returns_done(client):
    r = client.post("/api/print/text?wait=true", json={"lines": ["x"]})
    assert r.status_code == 200 and r.json()["status"] == "done"


def test_preview_matches_label_size(client):
    r = client.post("/api/preview/text", json={"lines": ["A"], "size": "4x6"})
    assert Image.open(BytesIO(r.content)).size == (812, 1218)


def test_print_raw_image(client):
    r = client.post("/api/print/image?size=2x1&copies=2", content=_png(), headers={"Content-Type": "image/png"})
    assert r.status_code == 202
    assert _wait_out(client)[0].read_bytes().endswith(b"PRINT 1,2\r\n")


def test_bad_image_and_size(client):
    r = client.post("/api/print/image", content=b"nope", headers={"Content-Type": "image/png"})
    assert r.status_code == 422
    r = client.post("/api/print/text", json={"lines": ["x"], "size": "9x9"})
    assert r.status_code == 422 and "unknown size" in r.json()["detail"]


def test_binsight_off_by_default(client):
    assert client.get("/api/config").json()["binsight"] is False
    r = client.post("/api/preview/binsight", json={"code": "183-JHL"})
    assert r.status_code == 404 and "not configured" in r.json()["detail"]


def test_binsight_fetches_label(tmp_path, monkeypatch):
    import urllib.request

    from labelqueue.main import create_app

    seen = {}

    class Resp(BytesIO):
        def __enter__(self):
            return self

        def __exit__(self, *a):
            return False

    def fake_urlopen(req, timeout):
        seen["url"] = req.full_url
        return Resp(_png(600, 900))

    monkeypatch.setattr(urllib.request, "urlopen", fake_urlopen)
    app = create_app(Settings(data_dir=tmp_path, binsight_url="http://binsight.test:8000"))
    with TestClient(app) as client:
        assert client.get("/api/config").json()["binsight"] is True
        r = client.post("/api/preview/binsight", json={"code": "183-jhl"})
        assert r.status_code == 200
        assert seen["url"] == "http://binsight.test:8000/api/labels/183-JHL/image"
        assert Image.open(BytesIO(r.content)).size == size_dots("2x3")  # binsight_size default
        assert client.post("/api/print/binsight", json={"code": "../etc"}).status_code == 422


def test_status_and_health(client):
    assert client.get("/healthz").json() == {"ok": True}
    assert client.get("/api/status").json()["transport"] == "file"
    assert "4x6" in client.get("/api/config").json()["sizes"]
    assert client.get("/").status_code == 200


def test_speed_is_sent_when_set():
    from PIL import Image
    from labelqueue import tspl
    job = tspl.bitmap_job(Image.new("1", (16, 8), 1), 50.8, 25.4, speed=2)
    assert b"SPEED 2\r\nDENSITY 8\r\n" in job


def test_image_margin_zero_prints_full_bleed(tmp_path):
    from io import BytesIO
    from fastapi.testclient import TestClient
    from PIL import Image
    from labelqueue.config import Settings
    from labelqueue.main import create_app
    black = BytesIO()
    Image.new("L", (900, 600), 0).save(black, format="PNG")
    with TestClient(create_app(Settings(data_dir=tmp_path, transport="file"))) as client:
        r = client.post("/api/preview/image?size=3x2&margin=0", content=black.getvalue(), headers={"Content-Type": "image/png"})
        assert r.status_code == 200
        img = Image.open(BytesIO(r.content)).convert("L")
        assert img.getpixel((0, 0)) == 0 and img.getpixel((img.width - 1, img.height - 1)) == 0
