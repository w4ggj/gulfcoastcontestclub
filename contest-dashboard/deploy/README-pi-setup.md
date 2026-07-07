# Pi Setup — GCCC Contest Collector

## Hardware
- Raspberry Pi 4 (2 GB+ RAM) on the contest LAN
- USB thumb drive (decent quality) for the SQLite DB — mount at `/media/usb/`
- Pi on a UPS or clean power strip so the display never drops

## Software install

```bash
# 1. Clone / pull the repo
git clone https://github.com/w4ggj/gulfcoastcontestclub.git ~/gulfcoastcontestclub

# 2. Create a Python venv
python3 -m venv ~/gccc-venv
source ~/gccc-venv/bin/activate
pip install -r ~/gulfcoastcontestclub/contest-dashboard/collector/requirements.txt

# 3. Mount the USB stick (add to /etc/fstab for auto-mount)
sudo mkdir -p /media/usb
# find your device: lsblk
# /etc/fstab entry example:
#   /dev/sda1  /media/usb  ext4  defaults,noatime  0 2

# 4. Install the systemd service
sudo cp ~/gulfcoastcontestclub/contest-dashboard/deploy/gccc-collector.service \
        /etc/systemd/system/
# Edit the service file — fill in SUPABASE_URL and SUPABASE_SERVICE_KEY if using cloud mirror
sudo nano /etc/systemd/system/gccc-collector.service
sudo systemctl daemon-reload
sudo systemctl enable --now gccc-collector

# Check it's running
sudo systemctl status gccc-collector
journalctl -u gccc-collector -f
```

## Stable LAN address

Pick one:
- **Reserved DHCP** — log in to your router, find the Pi's MAC, assign a fixed IP (e.g. `192.168.1.100`).
- **mDNS** — `sudo apt install avahi-daemon`, then the Pi is reachable at `gccc-contest.local`.

The kiosk URL is then `http://192.168.1.100:8080` or `http://gccc-contest.local:8080`.

## Kiosk laptop (display device)

```bash
# Install Chromium if needed (or use the built-in browser)
# Auto-launch on boot — add to ~/.config/autostart/kiosk.desktop:
[Desktop Entry]
Type=Application
Name=GCCC Dashboard Kiosk
Exec=chromium-browser --kiosk --noerrdialogs --disable-infobars http://gccc-contest.local:8080
X-GNOME-Autostart-enabled=true
```

Disable screen blanking:
```bash
xset s off; xset -dpms; xset s noblank
```

## N1MM configuration (every seat)

In N1MM: **Config → Configure Ports → Broadcast Data → Contacts**

- Enable: `ContactInfo`
- Send to: `192.168.1.255:12060`  ← subnet broadcast (`.255`) on port `12060`
- Use the **same config on every seat** — the Pi hears all of them on one socket.

Do **not** enable `LookupInfo` — it fires before the QSO is logged (on spacebar), not after.

## Verifying packets (§0 verify-first)

Run this on the Pi while N1MM is logging a test QSO to capture a real packet:

```bash
python3 - <<'EOF'
import socket, sys
s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
s.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
s.bind(('', 12060))
print("Listening on :12060 — log a QSO in N1MM…")
while True:
    data, addr = s.recvfrom(65535)
    print(f"\n=== from {addr} ===")
    print(data.decode('utf-8', errors='replace'))
EOF
```

Compare the XML element names to `collector/config.py → N1MM_FIELDS`. Update any that differ.
Also check `isoriginal` behavior across seats to confirm dedupe strategy (§0.2).

## Updates

```bash
cd ~/gulfcoastcontestclub
git pull
sudo systemctl restart gccc-collector
```
