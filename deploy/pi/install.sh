#!/bin/bash
# Name tag booth Pi setup: Raspberry Pi 5, Raspberry Pi OS (64-bit, with desktop,
# based on Debian 13 "Trixie" - Bookworm's PrusaSlicer is too old), touch display.
# Run from the cloned repository:
#
#   sudo deploy/pi/install.sh [--pin 2468] [--hotspot SSID PASSWORD] [--printer-ip 192.168.10.2] [--no-kiosk]
#   sudo deploy/pi/install.sh --readonly        # last step: read-only root
#   sudo deploy/pi/install.sh --writable        # undo, e.g. for an update
#
# Data (orders, tags, plates, backups, booth.json) lives on the partition labelled
# BOOTHDATA, mounted at /data. Everything else becomes read-only with --readonly,
# so pulling the plug is safe. Safe to run again (update, new PIN); see README.md.
set -euo pipefail

HERE="$(cd "$(dirname "$0")" && pwd)"
REPO="$(cd "$HERE/../.." && pwd)"
USER_NAME="${SUDO_USER:-}"
DATA=/data
PIN=""
HOTSPOT_SSID=""
HOTSPOT_PASS=""
PI_IP=192.168.10.1
PRINTER_IP=192.168.10.2
MODE=install
KIOSK=auto

while [ $# -gt 0 ]; do
    case "$1" in
        --pin) PIN="$2"; shift 2 ;;
        --user) USER_NAME="$2"; shift 2 ;;
        --hotspot) HOTSPOT_SSID="$2"; HOTSPOT_PASS="$3"; shift 3 ;;
        --printer-ip) PRINTER_IP="$2"; shift 2 ;;
        --no-kiosk) KIOSK=no; shift ;;
        --readonly) MODE=readonly; shift ;;
        --writable) MODE=writable; shift ;;
        -h|--help) sed -n '2,15p' "$0"; exit 0 ;;
        *) echo "unknown option $1" >&2; exit 2 ;;
    esac
done

[ "$(id -u)" -eq 0 ] || { echo "run with sudo" >&2; exit 1; }
[ -n "$USER_NAME" ] && [ "$USER_NAME" != root ] || { echo "run with sudo as the desktop user, or --user NAME" >&2; exit 1; }
USER_HOME="$(getent passwd "$USER_NAME" | cut -d: -f6)"
say() { printf '\n== %s\n' "$*"; }
as_user() { sudo -u "$USER_NAME" -H "$@"; }
overlay_active() { grep -q " / overlay" /proc/mounts; }

if [ "$MODE" = readonly ]; then
    findmnt -rn "$DATA" >/dev/null || { echo "$DATA is not mounted: orders would be lost. Stop." >&2; exit 1; }
    say "read-only root (overlay file system) and boot partition, active after a reboot"
    raspi-config nonint do_overlayfs 0
    raspi-config nonint enable_bootro 2>/dev/null \
        || echo "boot partition: set it read-only in raspi-config > Performance > Overlay File System"
    echo "Reboot now: sudo reboot. Changes to / are then lost at every restart; $DATA stays."
    exit 0
fi
if [ "$MODE" = writable ]; then
    say "root writable again, active after a reboot"
    raspi-config nonint do_overlayfs 1
    raspi-config nonint disable_bootro 2>/dev/null || true
    echo "Reboot, update (git pull, install.sh), then --readonly again."
    exit 0
fi
if overlay_active; then
    echo "The root file system is read-only (overlay): run --writable and reboot first." >&2
    exit 1
fi

. /etc/os-release
if [ "${VERSION_CODENAME:-}" = bookworm ]; then
    echo "WARNING: Bookworm ships PrusaSlicer 2.5, the booth needs 2.9 (Trixie)."
    echo "         The script falls back to PrusaSlicer from Flathub; a Trixie image is simpler."
fi

say "packages"
apt-get update
apt-get install -y python3-venv python3-pip git curl openscad nodejs npm fonts-noto-color-emoji   # emoji = icons on the staff page
# hwclock (staff page sets the clock): its own package since Trixie
apt-get install -y util-linux-extra 2>/dev/null || true
# Kiosk screen only on a desktop image (labwc); on Lite / headless: backend only,
# kiosk and staff page are then opened from another device's browser.
if [ "$KIOSK" = auto ]; then
    if command -v labwc >/dev/null || [ -e /usr/share/wayland-sessions/labwc.desktop ]; then KIOSK=yes; else KIOSK=no; fi
fi
if [ "$KIOSK" = yes ]; then
    apt-get install -y chromium || apt-get install -y chromium-browser
    CHROMIUM="$(command -v chromium || command -v chromium-browser)"
fi
apt-get install -y prusa-slicer || true
PS_VER="$( (prusa-slicer --help 2>/dev/null || true) | head -1 | sed -n 's/^PrusaSlicer-\([0-9]*\.[0-9]*\).*/\1/p')"
if [ -z "$PS_VER" ] || [ "$(printf '%s\n' 2.9 "$PS_VER" | sort -V | head -1)" != 2.9 ]; then
    say "PrusaSlicer ${PS_VER:-missing} is too old: installing 2.9 from Flathub"
    apt-get install -y flatpak
    flatpak remote-add --if-not-exists flathub https://dl.flathub.org/repo/flathub.flatpakrepo
    flatpak install -y --noninteractive flathub com.prusa3d.PrusaSlicer
    cat > /usr/local/bin/prusa-slicer-booth <<EOF
#!/bin/sh
# PrusaSlicer CLI from Flathub, with access to the booth data
exec flatpak run --filesystem=$DATA --filesystem=/tmp --filesystem=$REPO:ro --command=prusa-slicer com.prusa3d.PrusaSlicer "\$@"
EOF
    chmod 755 /usr/local/bin/prusa-slicer-booth
    echo "PRUSA_SLICER=/usr/local/bin/prusa-slicer-booth" > /etc/default/nametag-booth
else
    echo "PrusaSlicer $PS_VER from apt"
    : > /etc/default/nametag-booth
fi

say "data partition (label BOOTHDATA) at $DATA"
mkdir -p "$DATA"
if blkid -L BOOTHDATA >/dev/null; then
    if ! grep -q "LABEL=BOOTHDATA" /etc/fstab; then
        # data=journal + commit=1: an order written is on the card within a second
        echo "LABEL=BOOTHDATA $DATA ext4 defaults,noatime,data=journal,commit=1,nofail,x-systemd.device-timeout=5s 0 2" >> /etc/fstab
        systemctl daemon-reload
    fi
    findmnt -rn "$DATA" >/dev/null || mount "$DATA"
else
    # no fstab entry without the partition: the service needs $DATA mounted if it is
    # in fstab (RequiresMountsFor) and would never start
    if grep -q "LABEL=BOOTHDATA" /etc/fstab; then
        sed -i "/LABEL=BOOTHDATA/d" /etc/fstab
        systemctl daemon-reload
    fi
    echo "WARNING: no partition labelled BOOTHDATA. Orders would go to the root file system"
    echo "         and be lost once it is read-only. See README.md, 'Data partition'."
fi
mkdir -p "$DATA/nametag"
if [ ! -e "$DATA/nametag/booth.json" ]; then
    cp "$REPO/config/booth.json" "$DATA/nametag/booth.json"
    echo "booth.json copied to $DATA/nametag/ (staff settings are saved there)"
fi
chown -R "$USER_NAME:" "$DATA/nametag"

say "Python environment"
as_user python3 -m venv "$REPO/backend/.venv"
as_user "$REPO/backend/.venv/bin/pip" install -q --upgrade pip
as_user "$REPO/backend/.venv/bin/pip" install -q -r "$REPO/backend/requirements.txt"

say "kiosk build (frontend)"
as_user bash -c "cd '$REPO/frontend' && npm ci --no-audit --no-fund && npm run build"

say "staff PIN"
if [ -n "$PIN" ]; then
    as_user "$REPO/backend/.venv/bin/python" - "$DATA/nametag/booth.json" "$PIN" <<'EOF'
import json, re, sys
p, pin = sys.argv[1], sys.argv[2]
if not re.fullmatch(r"\d{4,8}", pin):
    sys.exit("PIN: 4 to 8 digits")
d = json.load(open(p)); d["staff_pin"] = pin
json.dump(d, open(p, "w"), indent=2, ensure_ascii=False)
print("PIN set")
EOF
else
    echo "PIN unchanged ($(grep -o '"staff_pin": *"[0-9]*"' "$DATA/nametag/booth.json" | grep -o '[0-9]*' || echo '?')); change with --pin or on the staff page"
fi

say "network: direct cable to the printer on eth0 ($PI_IP -> printer $PRINTER_IP)"
if command -v nmcli >/dev/null; then
    nmcli -t -f NAME con show | grep -qx booth-printer || \
        nmcli con add type ethernet ifname eth0 con-name booth-printer ipv4.method manual \
            ipv4.addresses "$PI_IP/24" ipv4.never-default yes ipv6.method disabled connection.autoconnect yes
    nmcli con up booth-printer >/dev/null 2>&1 || echo "eth0: no cable yet (fine)"
    if [ -n "$HOTSPOT_SSID" ]; then
        say "Wi-Fi hotspot '$HOTSPOT_SSID' for the staff phones"
        nmcli con delete booth-hotspot >/dev/null 2>&1 || true
        nmcli con add type wifi ifname wlan0 con-name booth-hotspot ssid "$HOTSPOT_SSID" \
            802-11-wireless.mode ap 802-11-wireless.band bg ipv4.method shared \
            wifi-sec.key-mgmt wpa-psk wifi-sec.psk "$HOTSPOT_PASS" connection.autoconnect yes \
            connection.autoconnect-priority 10
        echo "staff phones: Wi-Fi '$HOTSPOT_SSID', then http://10.42.0.1:8080/staff/"
    fi
else
    echo "NetworkManager not found: set eth0 to $PI_IP/24 by hand"
fi

say "service nametag-booth"
sed -e "s|@USER@|$USER_NAME|g" -e "s|@REPO@|$REPO|g" -e "s|@DATA@|$DATA|g" \
    "$HERE/nametag-booth.service" > /etc/systemd/system/nametag-booth.service
cat > /etc/sudoers.d/nametag-booth <<EOF
# booth staff page: shut down / restart, set the clock from a staff phone
$USER_NAME ALL=(root) NOPASSWD: /usr/bin/systemctl poweroff, /usr/bin/systemctl reboot, /usr/bin/date -s @*, /usr/sbin/hwclock -w
EOF
chmod 440 /etc/sudoers.d/nametag-booth
visudo -cf /etc/sudoers.d/nametag-booth
systemctl daemon-reload
systemctl enable nametag-booth
systemctl restart nametag-booth

if [ "$KIOSK" = yes ]; then
say "desktop: autologin, no screen blanking, kiosk browser"
raspi-config nonint do_boot_behaviour B4      # desktop, automatic login
raspi-config nonint do_blanking 1             # 1 = blanking off
install -m 755 "$HERE/kiosk.sh" /usr/local/bin/nametag-kiosk
sed -i "s|^CHROMIUM=.*|CHROMIUM=\"$CHROMIUM\"|" /usr/local/bin/nametag-kiosk
AUTOSTART="$USER_HOME/.config/labwc/autostart"
as_user mkdir -p "$(dirname "$AUTOSTART")"
touch "$AUTOSTART"
grep -q nametag-kiosk "$AUTOSTART" || echo "/usr/local/bin/nametag-kiosk &" >> "$AUTOSTART"
chown "$USER_NAME:" "$AUTOSTART"
if [ -e "$USER_HOME/.config/wayfire.ini" ] && ! pgrep -x labwc >/dev/null; then
    echo "NOTE: this desktop may run wayfire, not labwc: switch with raspi-config (Advanced > Wayland > labwc)"
fi
else
    say "no desktop (Lite image or --no-kiosk): kiosk screen skipped, open http://<this Pi>:8080/kiosk/ in a browser"
fi

say "self-check"
for i in $(seq 1 20); do curl -fs http://127.0.0.1:8080/api/config >/dev/null && break; sleep 1; done
curl -fs http://127.0.0.1:8080/api/config >/dev/null && echo "backend answers on :8080" \
    || echo "backend does not answer yet: journalctl -u nametag-booth"
set -a; . /etc/default/nametag-booth; set +a
as_user env BOOTH_DATA="$DATA/nametag" BOOTH_CONFIG="$DATA/nametag/booth.json" PRUSA_SLICER="${PRUSA_SLICER:-}" \
    "$REPO/backend/.venv/bin/python" "$REPO/tools/selfcheck.py" --data "$DATA/nametag/selfcheck" || true

cat <<EOF

Done. Reboot to start the kiosk: sudo reboot
Staff page: http://<this Pi>:8080/staff/  (on the kiosk: tap the top-left corner 5 times)
At the booth: printer settings on the staff page (Einstellungen > Drucker > Verbindung testen).
When everything works: sudo $0 --readonly
EOF
