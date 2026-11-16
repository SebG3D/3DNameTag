#!/usr/bin/env python3
"""Second booth screen for the staff page (called by install.sh --staff-screen / --no-staff-screen).

Customer kiosk on one HDMI screen, staff page on the other. Run as root:

    screens.py --user sebmin --staff HDMI-A-2     # or --staff auto
    screens.py --user sebmin --off                # back to one screen

What it writes:
  * labwc window rules (in the user's ~/.config/labwc/rc.xml, between marker
    comments): app id nametag-kiosk -> kiosk screen, nametag-staff -> staff screen.
  * udev rule /etc/udev/rules.d/99-nametag-touch.rules: each touch panel gets a
    LIBINPUT_CALIBRATION_MATRIX that squeezes it onto its own screen, keyed by the
    USB port (both panels may report the same name, e.g. "ILITEK ILITEK-TP", so
    labwc's <touch deviceName mapToOutput> can't tell them apart, and labwc 0.20
    ignores WL_OUTPUT: an unmapped touch panel spans the whole desktop, i.e. both
    screens). Which panel is which is found by asking for a tap on the staff screen.
    So: do not swap the touch USB cables afterwards (if you do, run this again).
  * kanshi profile ~/.config/kanshi/config: fixed layout, kiosk left, staff right.
    Without it labwc arranges the screens in the order they come up, which can
    flip between boots, and the calibration (left/right half) then sends every
    tap to the other screen.
  * autostart line "nametag-kiosk staff".
Takes effect after a reboot.
"""
import argparse, glob, json, os, pwd, re, select, shutil, subprocess, sys, time

UDEV_RULE = "/etc/udev/rules.d/99-nametag-touch.rules"
BEGIN, END = "<!-- nametag-screens begin -->", "<!-- nametag-screens end -->"
STAFF_LINE = "/usr/local/bin/nametag-kiosk staff &"
KANSHI_MARK = "# nametag booth (deploy/pi/screens.py)"


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


def output_boxes(user, uid):
    """{output: (x, y, w, h)} in desktop (layout) coordinates, from the running labwc."""
    env = {"WAYLAND_DISPLAY": "wayland-0", "XDG_RUNTIME_DIR": f"/run/user/{uid}", "PATH": os.environ.get("PATH", "")}
    r = subprocess.run(["sudo", "-u", user, "env", *[f"{k}={v}" for k, v in env.items()], "wlr-randr", "--json"],
                       capture_output=True, text=True)
    if r.returncode:
        sys.exit("wlr-randr failed (is the desktop running on the screens?): " + r.stderr.strip())
    boxes = {}
    for o in json.loads(r.stdout):
        mode = next((m for m in o.get("modes", []) if m.get("current")), None)
        if not o.get("enabled") or not mode:
            continue
        w, h = mode["width"] / o.get("scale", 1), mode["height"] / o.get("scale", 1)
        if o.get("transform") in ("90", "270", "flipped-90", "flipped-270"):
            w, h = h, w
        boxes[o["name"]] = (o["position"]["x"], o["position"]["y"], w, h)
    return boxes


def matrix(box, boxes):
    """libinput calibration matrix: whole panel (0..1) -> box inside the desktop bounding box."""
    x0 = min(b[0] for b in boxes.values()); y0 = min(b[1] for b in boxes.values())
    W = max(b[0] + b[2] for b in boxes.values()) - x0
    H = max(b[1] + b[3] for b in boxes.values()) - y0
    x, y, w, h = box
    f = lambda v: f"{v:.6g}"
    return " ".join(map(f, (w / W, 0, (x - x0) / W, 0, h / H, (y - y0) / H)))


def write_udev(mapping):
    """mapping: {ID_PATH: (output, calibration matrix)}; empty -> remove the rule."""
    if not mapping:
        if os.path.exists(UDEV_RULE):
            os.remove(UDEV_RULE)
    else:
        lines = ["# nametag booth: touch panel -> screen by USB port (deploy/pi/screens.py)"]
        for path, (out, m) in mapping.items():
            lines.append(f"# -> {out}")
            lines.append(f'ACTION=="add|change", SUBSYSTEM=="input", ENV{{ID_INPUT_TOUCHSCREEN}}=="1", '
                         f'ENV{{ID_PATH}}=="{path}", ENV{{LIBINPUT_CALIBRATION_MATRIX}}="{m}"')
        open(UDEV_RULE, "w").write("\n".join(lines) + "\n")
    subprocess.run(["udevadm", "control", "--reload"], check=False)
    subprocess.run(["udevadm", "trigger", "--subsystem-match=input", "--action=change"], check=False)


def pinned_boxes(boxes, kiosk, staff):
    """layout we pin with kanshi: kiosk at 0,0, staff to its right (top aligned)."""
    kx, ky, kw, kh = boxes[kiosk]
    _, _, sw, sh = boxes[staff]
    return {kiosk: (0, 0, kw, kh), staff: (int(kw), 0, sw, sh)}


def write_kanshi(home, uid, gid, layout):
    """layout {output: box} -> kanshi profile; None -> remove ours (a foreign config stays)."""
    path = os.path.join(home, ".config/kanshi/config")
    old = open(path).read() if os.path.exists(path) else ""
    if old.strip() and not old.startswith(KANSHI_MARK):
        shutil.copy(path, path + ".bak")
    if layout is None:
        if old.startswith(KANSHI_MARK):
            open(path, "w").write("")
        return
    os.makedirs(os.path.dirname(path), exist_ok=True)
    outs = "".join(f"  output {o} enable position {int(b[0])},{int(b[1])}\n" for o, b in layout.items())
    open(path, "w").write(f"{KANSHI_MARK}: fixed layout, kiosk left, staff right;\n"
                          f"# the touch calibration (udev 99-nametag-touch.rules) relies on it\n"
                          f"profile nametag {{\n{outs}}}\n")
    os.chown(path, uid, gid)
    os.chown(os.path.dirname(path), uid, gid)


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
        write_kanshi(home, uid, gid, None)
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

    boxes = output_boxes(a.user, uid)
    if staff not in boxes or kiosk not in boxes:
        sys.exit(f"screens not active in the desktop: {boxes}")
    boxes = pinned_boxes(boxes, kiosk, staff)
    print("desktop layout (pinned):", ", ".join(f"{k} {int(v[2])}x{int(v[3])}+{v[0]}+{v[1]}" for k, v in boxes.items()))
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
            out = staff if d == dev else kiosk
            mapping[path] = (out, matrix(boxes[out], boxes))
        if len(set(mapping)) < len(touch):
            print("NOTE: two touch panels share one USB path, mapping may be wrong")

    write_rc(home, uid, gid, kiosk, staff)
    write_udev(mapping)
    write_kanshi(home, uid, gid, boxes)
    set_autostart(home, uid, gid, True)
    print("staff screen set up (screen layout, window rules, touch mapping, autostart): reboot to apply")


if __name__ == "__main__":
    main()
