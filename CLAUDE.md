# labelqueue

Print server and web UI for Bluetooth TSPL thermal label printers. Usage, API and install: README.md.

## Conventions
- Runtime dependencies come from Debian 13 apt packages, not pip. Keep `pyproject.toml` pinned to Debian's versions, and add a dependency only if Debian packages it (then add it to `PKGS` in `deploy/install.sh`).
- Run `uv run pytest` before committing. The `file` transport writes jobs to `data/out/`, so everything except the radio can be tested without a printer.
- The preview must stay the exact bitmap that prints: render once, then send that image to both the preview and `tspl.bitmap_job`.
- Printer settings live in `/etc/labelqueue/labelqueue.env` on the host, never in the repo. Defaults are in `deploy/labelqueue.env.example`.
- Integrations (Binsight) are off unless configured. Nothing about any particular deployment (hosts, IPs, MACs, domains) belongs in this repo.
