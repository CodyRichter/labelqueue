# labelqueue

A small print server and web UI for Bluetooth thermal label printers that speak TSPL (JADENS, iDPRT, Munbyn and most cheap 4×6 shipping-label printers). No vendor app is involved: every label is rendered to a 1-bit bitmap at 203 dpi, queued, and sent to the printer over Bluetooth Classic (RFCOMM) or BLE.

- **Web UI:** Text (optional QR) and Image (drop, choose or paste) tabs. The preview is the exact bitmap that will print.
- **HTTP API:** for scripts, Home Assistant or any other service.
- **Queue and history:** jobs print one at a time, and the last 200 are kept with their previews.
- **Optional [Binsight](https://github.com/CodyRichter/binsight) tab:** prints a Binsight location's QR label by its code. It's shown only when `BINSIGHT_URL` is set.

## API
There is no authentication. Run it on a network you trust.

```sh
# text, optional QR
curl -X POST http://localhost:8000/api/print/text -H 'Content-Type: application/json' \
  -d '{"lines":["Leftovers","Chicken curry","Nov 22"],"qr":"https://example.com","size":"3x2","source":"me"}'
# an image: raw body, options in the query
curl -X POST 'http://localhost:8000/api/print/image?size=4x6&fit=contain&rotate=auto&dither=false' \
  -H 'Content-Type: image/png' --data-binary @label.png
# an image by URL
curl -X POST http://localhost:8000/api/print/image -H 'Content-Type: application/json' -d '{"url":"https://…/label.png"}'
# a Binsight location's label (needs BINSIGHT_URL)
curl -X POST http://localhost:8000/api/print/binsight -H 'Content-Type: application/json' -d '{"code":"K7Q-4MZ"}'
```

Print calls return `202 {"id": …, "status": "queued"}`. Add `?wait=true` to wait up to 30 s for the result (`200` done, `502` with `error` if the printer failed). Image endpoints take `margin` in dots (default 16). Every `/api/print/*` has a `/api/preview/*` twin that returns the PNG instead. Also: `GET /api/status`, `/api/config` (sizes), `/api/jobs`, `/api/jobs/{id}/preview.png`, `POST /api/selftest`, `GET /healthz`.

Sizes are named in inches, width × height as the stock feeds: `4x6 4x3 3x2 2x3 2x1 2.25x1.25` (`labelqueue/config.py`).

## Install (Debian 13)
The server runs from Debian's own packages (`python3-fastapi`, `-uvicorn`, `-pil`, `-segno`, `-bleak`), so unattended-upgrades keeps them patched. It runs as a systemd service rather than in a container, because Bluetooth from a container needs host networking and BlueZ's D-Bus.

```sh
git clone https://github.com/CodyRichter/labelqueue && cd labelqueue
sudo deploy/install.sh        # apt packages, user, /opt/labelqueue, systemd unit; safe to re-run
labelqueue-probe scan         # find the printer's MAC
labelqueue-probe info <mac>   # classic SPP channel and/or BLE characteristics
sudo $EDITOR /etc/labelqueue/labelqueue.env && sudo systemctl restart labelqueue
```

`/etc/labelqueue/labelqueue.env` is created once from `deploy/labelqueue.env.example` and never overwritten. It sets the transport (`file`, `rfcomm` or `ble`), the printer MAC, the RFCOMM channel or BLE characteristic, default sizes, density, speed, gap and x offset. With the `file` transport nothing prints, and jobs land in `/var/lib/labelqueue/out`. The web UI is on port 8000.

## Develop
```sh
uv sync --group dev && uv run pytest
LABELQUEUE_DATA=./data uv run uvicorn --factory labelqueue.main:create_app --reload   # file transport, jobs land in data/out
```

- `labelqueue/`: the app (FastAPI). `render.py` turns images and text into bitmaps, `tspl.py` encodes them, `transport.py` sends them (`file`, `rfcomm`, `ble`), `jobs.py` is the queue and history, and `static/` is the UI.
- `deploy/`: `install.sh`, the systemd unit and the env file template.
- `tools/probe.sh`: installed as `labelqueue-probe`, for finding the printer and testing transports.

## License
MIT
