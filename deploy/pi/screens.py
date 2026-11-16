#!/usr/bin/env python3
"""Second booth screen for the staff page (called by install.sh --staff-screen / --no-staff-screen).

Customer kiosk on one HDMI screen, staff page on the other. Run as root:

    screens.py --user sebmin --staff HDMI-A-2     # or --staff auto
    screens.py --user sebmin --off                # back to one screen

What it writes:
  * labwc window rules (in the user's ~/.config/labwc/rc.xml, between marker
    comments): app id nametag-kiosk -> kiosk screen, nametag-staff -> staff screen.
  * udev rule /etc/udev/rules.d/99-nametag-touch.rules: each touch panel gets
    WL_OUTPUT=<its screen>, keyed by the USB port (both panels may report the same
    name, e.g. "ILITEK ILITEK-TP"). labwc maps a touch device to its WL_OUTPUT.
    Which panel is which is found by asking for a tap on the staff screen.
    So: do not swap the touch USB cables between ports afterwards.
  * autostart line "nametag-kiosk staff".
Takes effect after a reboot.
"""
import argparse, glob, os, pwd, re, select, shutil, subprocess, sys, time

UDEV_RULE = "/etc/udev/rules.d/99-nametag-touch.rules"
BEGIN, END = "<!-- nametag-screens begin -->", "<!-- nametag-screens end -->"
STAFF_LINE = "/usr/local/bin/nametag-kiosk staff &"


def connected_outputs():
    outs = []
    for d in sorted(glob.glob("/sys/class/drm/card*-*")):
        name = os.path.basename(d).split("-", 1)[1]
        try:
            if open(os.path.join(d, "status")).read().strip() == "connected" and not name.startswith("Writeback"):
                outs.append(name)
        except OSError:
            pass
    return outs


def touchscreens():
    """{event device: USB ID_PATH} for every touch screen."""
    found = {}
    for dev in sorted(glob.glob("/dev/input/event*")):
        info = subprocess.run(["udevadm", "info", "-q", "property", dev], capture_output=True, text=True).stdout
        props = dict(l.split("=", 1) for l in info.splitlines() if "=" in l)
        if props.get("ID_INPUT_TOUCHSCREEN") == "1" and props.get("ID_PATH"):
            found[dev] = props["ID_PATH"]
    return found


def wait_for_tap(devs, seconds=90):
    fds = {os.open(d, os.O_RDONLY | os.O_NONBLOCK): d for d in devs}
    end = time.time() + seconds
    try:
        while time.time() < end:
            ready, _, _ = select.select(list(fds), [], [], 1)
            for fd in ready:
                try:
                    if os.read(fd, 4096):
                        return fds[fd]
                except BlockingIOError:
                    pass
    finally:
        for fd in fds:
            os.close(fd)
    return None


def write_udev(mapping):
    """mapping: {ID_PATH: output}; empty -> remove the rule."""
    if not mapping:
        if os.path.exists(UDEV_RULE):
            os.remove(UDEV_RULE)
    else:
        lines = ["# nametag booth: touch panel -> screen by USB port (deploy/pi/screens.py)"]
        for path, out in mapping.items():
            lines.append(f'ACTION=="add|change", SUBSYSTEM=="input", ENV{{ID_INPUT_TOUCHSCREEN}}=="1", '
                         f'ENV{{ID_PATH}}=="{path}", ENV{{WL_OUTPUT}}="{out}"')
        open(UDEV_RULE, "w").write("\n".join(lines) + "\n")
    subprocess.run(["udevadm", "control", "--reload"], check=False)
    subprocess.run(["udevadm", "trigger", "--subsystem-match=input", "--action=change"], check=False)


def rule(app_id, output):
    # Chromium --kiosk is already full screen when mapped, and labwc does not move
    # full-screen windows: leave full screen, move, full screen again.
    return (f'    <windowRule identifier="{app_id}">\n'
            f'      <action name="ToggleFullscreen" />\n'
            f'      <action name="MoveToOutput" output="{output}" />\n'
            f'      <action name="ToggleFullscreen" />\n'
            f'    </windowRule>\n')


def write_rc(home, uid, gid, kiosk_out, staff_out):
    rc = os.path.join(home, ".config/labwc/rc.xml")
    os.makedirs(os.path.dirname(rc), exist_ok=True)
    if not os.path.exists(rc):
        # labwc reads only the first rc.xml it finds: start from the system one (Pi theme, keys)
        shutil.copy("/etc/xdg/labwc/rc.xml", rc)
    s = open(rc).read()
    s = re.sub(r"\s*" + re.escape(BEGIN) + r".*?" + re.escape(END), "", s, flags=re.S)
    if kiosk_out and staff_out:
        block = (f"  {BEGIN}\n  <windowRules>\n" + rule("nametag-kiosk", kiosk_out)
                 + rule("nametag-staff", staff_out) + f"  </windowRules>\n  {END}\n")
        if "</openbox_config>" not in s:
            sys.exit(f"{rc}: no </openbox_config>, not touching it")
        s = s.replace("</openbox_config>", block + "</openbox_config>")
    open(rc, "w").write(s)
    os.chown(rc, uid, gid)


def set_autostart(home, uid, gid, on):
    path = os.path.join(home, ".config/labwc/autostart")
    lines = open(path).read().splitlines() if os.path.exists(path) else []
    lines = [l for l in lines if l.strip() != STAFF_LINE]
    if on:
        lines.append(STAFF_LINE)
    open(path, "w").write("\n".join(lines) + "\n")
    os.chown(path, uid, gid)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--user", required=True)
    ap.add_argument("--staff", help="staff screen output, e.g. HDMI-A-2, or auto")
    ap.add_argument("--off", action="store_true")
    a = ap.parse_args()
    if os.geteuid() != 0:
        sys.exit("run as root")
    pw = pwd.getpwnam(a.user)
    home, uid, gid = pw.pw_dir, pw.pw_uid, pw.pw_gid

    if a.off:
        write_rc(home, uid, gid, None, None)
        write_udev({})
        set_autostart(home, uid, gid, False)
        print("staff screen off: kiosk only (reboot)")
        return

    outs = connected_outputs()
    print("connected screens:", ", ".join(outs) or "none")
    staff = a.staff
    if not staff or staff == "auto":
        staff = "HDMI-A-2" if "HDMI-A-2" in outs else (outs[-1] if len(outs) > 1 else None)
    others = [o for o in outs if o != staff]
    if not staff or staff not in outs or not others:
        sys.exit(f"need two connected screens (staff screen {staff!r}); connect both and retry")
    kiosk = "HDMI-A-1" if "HDMI-A-1" in others else others[0]
    print(f"customer kiosk: {kiosk}   staff page: {staff}")

    touch = touchscreens()
    mapping = {}
    if not touch:
        print("no touch screen found: windows are placed, touch not mapped")
    else:
        print(f"\n>>> Tap the STAFF screen ({staff}) now, a few times (90 s) <<<", flush=True)
        dev = wait_for_tap(touch)
        if not dev:
            sys.exit("no tap seen: run again")
        print(f"staff touch: {dev} (USB {touch[dev]})")
        for d, path in touch.items():
            mapping[path] = staff if d == dev else kiosk
        if len(set(mapping)) < len(touch):
            print("NOTE: two touch panels share one USB path, mapping may be wrong")

    write_rc(home, uid, gid, kiosk, staff)
    write_udev(mapping)
    set_autostart(home, uid, gid, True)
    print("staff screen set up (window rules, touch mapping, autostart): reboot to apply")


if __name__ == "__main__":
    main()
