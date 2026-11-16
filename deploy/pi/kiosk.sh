#!/bin/bash
# Booth screen: wait for the backend, then Chromium full screen on the touch display.
# Started from the desktop autostart (install.sh); restarts Chromium if it is closed.
#   nametag-kiosk          customer screen (/kiosk/)
#   nametag-kiosk staff    staff screen (/staff/), only with install.sh --staff-screen
# Each window gets its own app id (nametag-kiosk / nametag-staff); the labwc window
# rules written by install.sh move it to its screen.
CHROMIUM=chromium
ROLE="${1:-kiosk}"
case "$ROLE" in
    kiosk) URL="http://127.0.0.1:8080/kiosk/" ;;
    staff) URL="http://127.0.0.1:8080/staff/" ;;
    *) echo "usage: $0 [kiosk|staff]" >&2; exit 2 ;;
esac

until curl -fs http://127.0.0.1:8080/api/config >/dev/null; do sleep 1; done

while true; do
    # Fresh profile in RAM: nothing to restore, no "Chromium didn't shut down correctly"
    PROFILE="$(mktemp -d "/tmp/nametag-chromium-$ROLE.XXXXXX")"
    "$CHROMIUM" --kiosk --class="nametag-$ROLE" --noerrdialogs --disable-infobars --no-first-run \
        --disable-session-crashed-bubble --disable-features=Translate,TouchpadOverscrollHistoryNavigation \
        --overscroll-history-navigation=0 --disable-pinch --password-store=basic \
        --autoplay-policy=no-user-gesture-required \
        --user-data-dir="$PROFILE" --check-for-update-interval=31536000 \
        --ozone-platform=wayland "$URL"
    rm -rf "$PROFILE"
    sleep 2
done
