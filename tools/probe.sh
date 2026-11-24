#!/bin/sh
# Find the printer and work out how it talks. Runs as root on the print server (installed as labelqueue-probe).
#   labelqueue-probe scan                 15 s scan, then list likely printers
#   labelqueue-probe info <mac>           classic profiles (UUIDs) + BLE GATT characteristics
#   labelqueue-probe rfcomm <mac> [ch]    send a TSPL test label over classic SPP (default channel 1)
#   labelqueue-probe ble <mac> <char>     send a TSPL test label over BLE to a writable characteristic
#   labelqueue-probe selftest-rfcomm|selftest-ble ...   same, but TSPL SELFTEST
set -e
cmd=${1:-scan}; mac=$2

test_job() {
  if [ "${SELFTEST:-}" = 1 ]; then printf 'SELFTEST\r\n'; return; fi
  printf 'SIZE 100 mm,150 mm\r\nGAP 2 mm,0 mm\r\nDIRECTION 1\r\nCLS\r\nTEXT 40,40,"4",0,1,1,"labelqueue test"\r\nBOX 30,30,780,140,4\r\nPRINT 1,1\r\n'
}

case "$cmd" in
  scan)
    bluetoothctl power on >/dev/null
    bluetoothctl --timeout 15 scan on >/dev/null 2>&1 || true
    echo "Likely printers:"
    bluetoothctl devices | grep -iE 'jadens|jd-|print|prt|label|thermal|tspl|ship' || echo "  (none by name; full list below)"
    echo; echo "All named devices:"; bluetoothctl devices | grep -vE 'Device ([0-9A-F]{2}[:-]){5}[0-9A-F]{2} ([0-9A-F]{2}-){5}[0-9A-F]{2}$'
    ;;
  info)
    [ -n "$mac" ] || { echo "usage: $0 info <mac>"; exit 2; }
    bluetoothctl info "$mac"
    if command -v sdptool >/dev/null; then echo; echo "== SDP (classic) =="; sdptool browse "$mac" | grep -E 'Service Name|Channel|0x1101' || true; fi
    echo; echo "== BLE GATT (connect, list, disconnect) =="
    bluetoothctl --timeout 10 connect "$mac" >/dev/null 2>&1 || true
    bluetoothctl --timeout 5 gatt.list-attributes "$mac" 2>/dev/null | grep -B1 -A2 -iE 'characteristic' || echo "(no GATT attributes: probably classic only)"
    bluetoothctl disconnect "$mac" >/dev/null 2>&1 || true
    ;;
  rfcomm|selftest-rfcomm)
    [ "$cmd" = selftest-rfcomm ] && SELFTEST=1
    test_job | python3 -c '
import socket, sys
mac, ch = sys.argv[1], int(sys.argv[2])
s = socket.socket(socket.AF_BLUETOOTH, socket.SOCK_STREAM, socket.BTPROTO_RFCOMM)
s.settimeout(15); s.connect((mac, ch)); s.sendall(sys.stdin.buffer.read()); s.close(); print("sent over rfcomm", mac, ch)
' "$mac" "${3:-1}"
    ;;
  ble|selftest-ble)
    [ "$cmd" = selftest-ble ] && SELFTEST=1
    [ -n "$3" ] || { echo "usage: $0 ble <mac> <char-uuid>"; exit 2; }
    test_job | python3 -c '
import asyncio, sys
from bleak import BleakClient
mac, char, data = sys.argv[1], sys.argv[2], sys.stdin.buffer.read()
async def main():
    async with BleakClient(mac, timeout=20) as c:
        for i in range(0, len(data), 180):
            await c.write_gatt_char(char, data[i:i+180], response=False); await asyncio.sleep(0.01)
    print("sent over ble", mac, char)
asyncio.run(main())
' "$mac" "$3"
    ;;
  *) sed -n 2,8p "$0"; exit 2 ;;
esac
