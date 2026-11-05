#!/bin/bash
# Booth screen: wait for the backend, then Chromium full screen on the touch display.
# Started from the desktop autostart (install.sh); restarts Chromium if it is closed.
CHROMIUM=chromium
URL="http://127.0.0.1:8080/kiosk/"

until curl -fs http://127.0.0.1:8080/api/config >/dev/null; do sleep 1; done

while true; do
    # Fresh profile in RAM: nothing to restore, no "Chromium didn't shut down correctly"
    PROFILE="$(mktemp -d /tmp/nametag-chromium.XXXXXX)"
    "$CHROMIUM" --kiosk --noerrdialogs --disable-infobars --no-first-run \
        --disable-session-crashed-bubble --disable-features=Translate,TouchpadOverscrollHistoryNavigation \
        --overscroll-history-navigation=0 --disable-pinch --password-store=basic \
        --autoplay-policy=no-user-gesture-required \
        --user-data-dir="$PROFILE" --check-for-update-interval=31536000 \
        --ozone-platform=wayland "$URL"
    rm -rf "$PROFILE"
    sleep 2
done
