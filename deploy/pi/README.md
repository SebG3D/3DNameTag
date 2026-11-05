# Booth Pi: setup

Raspberry Pi 5 + touch display (landscape), Prusa Core One on a direct network cable.
After setup the Pi boots straight into the kiosk; with `--readonly` the system is
read-only, so pulling the plug is safe. Orders, tags, plates, backups and the booth
settings live on a separate data partition (`/data`).

Adapted from the Nihtlight star booth (`Nihtlight/TestFixture/Booth/pi`). **Not tried on a
real Pi yet** – expect small fixes on the first install.

## 1. SD card

1. Raspberry Pi Imager: **Raspberry Pi OS (64-bit) with desktop, based on Debian 13
   "Trixie"** (Bookworm's PrusaSlicer 2.5 is too old for our profiles; the script would
   fall back to Flathub). In the settings: user (e.g. `booth`), Wi-Fi with internet for
   the installation, SSH on.
2. **Data partition** before the first boot (Linux PC with GParted):
   shrink `rootfs` so about 4 GB are free behind it, new partition there: ext4, label
   **`BOOTHDATA`**. Raspberry Pi OS grows the root partition to the whole card at its
   first boot – create the data partition **before** that.
   (Alternative: an ext4 USB stick labelled `BOOTHDATA`, always plugged in.)
3. **Clock:** fit the RTC battery (Pi 5, J5) and let the Pi charge it:
   `dtparam=rtc_bbat_vchg=3000000` in `/boot/firmware/config.txt`. The booth has no
   internet; without the battery the Pi starts with a wrong time (pickup numbers restart
   per day, pickup times). The staff page warns when the Pi's clock is off and sets it
   from the phone with one tap.

## 2. Install

On the Pi, with internet:

```sh
git clone https://github.com/SebG3D/3DNameTag.git ~/3DNameTag
cd ~/3DNameTag
sudo deploy/pi/install.sh --pin 2468 --hotspot Namensanhaenger geheim123
sudo reboot
```

| | |
|---|---|
| packages | python3-venv, git, curl, openscad, nodejs/npm, chromium, prusa-slicer (≥ 2.9, else Flathub) |
| `/data` | mounts `BOOTHDATA` (`data=journal,commit=1`), `/data/nametag/` = data dir + `booth.json` (copied from `config/` once; staff settings are saved there) |
| Python | `backend/.venv` with `backend/requirements.txt` |
| kiosk | `npm ci && npm run build` in `frontend/` |
| PIN | `--pin` writes it into `/data/nametag/booth.json`; without it the PIN stays (default 2468!) |
| network | `eth0` static `192.168.10.1/24` for the printer cable (`--printer-ip`, default printer `192.168.10.2`); `--hotspot SSID PASSWORD` makes a Wi-Fi for the staff phones (Pi = `10.42.0.1`) |
| service | `nametag-booth.service`: backend on `0.0.0.0:8080`, restarts by itself, `BOOTH_ALLOW_SYSTEM=1` |
| sudo | the booth user may `systemctl poweroff/reboot`, `date -s`, `hwclock -w` (staff page) |
| desktop | autologin, no screen blanking, `nametag-kiosk` in labwc autostart: waits for the backend, Chromium in kiosk mode on `/kiosk/`, restarted if closed |
| check | runs `tools/selfcheck.py` (tools, render + slice a test plate with timings, printer) |

Run it again any time (update, new PIN); it only changes what is needed.

## 3. Printer (Core One)

1. Printer menu › Settings › Network › Ethernet: **static IP `192.168.10.2`**, mask
   `255.255.255.0`. Cable printer ↔ Pi.
2. Printer menu › Settings › Network › PrusaLink: on; note **user** (`maker`) and **password**.
3. **USB stick** into the printer (plates are uploaded there).
4. Staff page › ⚙ Einstellungen › Drucker: *Prusa Core One (PrusaLink)*, host `192.168.10.2`,
   user, password → **Verbindung testen** must say "Drucker bereit … USB ok" → Speichern.
5. First real plate: watch the colour change (M600) and the end; after "Platte leer"
   the printer may still show the finished print – confirm it on the printer screen.
   If a plate start fails with "Drucker nicht bereit (409)", that confirmation is needed
   before each plate: then tell me, the backend can be changed to wait for it.

## 4. Morning of the booth

```sh
cd ~/3DNameTag && backend/.venv/bin/python tools/selfcheck.py      # over SSH, optional
```
Staff page › ⚙ Einstellungen: base colour of the day, text colours on the table, prices.
Staff page › 📊 Tag at the end: *Tag abschließen*, then *Herunterfahren*.

## 5. Read-only

When everything works:

```sh
sudo ~/3DNameTag/deploy/pi/install.sh --readonly && sudo reboot
```

**Updating later:** `install.sh --writable`, reboot, `git pull`, `install.sh`, test,
`install.sh --readonly`, reboot. Booth settings are on `/data` and survive.

## Notes

- **Logs:** `journalctl -u nametag-booth` (in RAM while read-only).
- **Backups:** `/data/nametag/backups/` (hourly + at day close, 48 kept). For a copy on a
  USB stick set `BOOTH_BACKUP_DIR=/media/...` in `/etc/default/nametag-booth`.
- **Exit the kiosk** (keyboard): Alt+F4 closes Chromium, it comes back after 2 s; to stop
  it for good: `pkill -f nametag-kiosk` over SSH.
- **Dry run without printer:** keep the printer type *Simulator*; or run the fake printer
  on a laptop (`python -m booth.fakelink --host 0.0.0.0 --port 8081`) and point the booth
  at `<laptop>:8081`, user `maker`, password `secret`.
