#!/bin/sh
# Install or update labelqueue on a Debian 13 host with BlueZ. Run as root from an unpacked
# checkout: `sudo deploy/install.sh`. Idempotent; /etc/labelqueue/labelqueue.env is created once
# from the example and never overwritten.
set -e
cd "$(dirname "$0")/.."
PKGS="python3-fastapi python3-uvicorn python3-pil python3-segno python3-bleak fonts-dejavu-core"
export DEBIAN_FRONTEND=noninteractive
dpkg -s $PKGS >/dev/null 2>&1 || { apt-get update -qq && apt-get install -y -qq $PKGS >/dev/null; }
id labelqueue >/dev/null 2>&1 || useradd --system --home /var/lib/labelqueue --shell /usr/sbin/nologin labelqueue
mkdir -p /opt/labelqueue /etc/labelqueue
rm -rf /opt/labelqueue/labelqueue
cp -R labelqueue /opt/labelqueue/
find /opt/labelqueue -name __pycache__ -prune -exec rm -rf {} +
install -m 644 deploy/labelqueue.service /etc/systemd/system/labelqueue.service
install -m 644 deploy/labelqueue.env.example /etc/labelqueue/labelqueue.env.example
install -m 755 tools/probe.sh /usr/local/bin/labelqueue-probe
[ -f /etc/labelqueue/labelqueue.env ] || cp /etc/labelqueue/labelqueue.env.example /etc/labelqueue/labelqueue.env
systemctl daemon-reload
systemctl enable labelqueue >/dev/null 2>&1
systemctl restart labelqueue
for i in $(seq 1 20); do curl -fs http://127.0.0.1:8000/healthz >/dev/null && break; sleep 0.5; done
curl -fs http://127.0.0.1:8000/api/status && echo
