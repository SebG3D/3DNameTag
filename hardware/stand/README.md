# Touchscreen stand

Two printed side brackets plus a 6 mm plywood/MDF plate, tilted 30°, standing on a plywood bottom plate. The space between the brackets has room for the Pi. The screen is glued (VHB) or screwed onto the plate.

**Before printing:** measure the screen and set `screen_w`, `screen_h` (outer size incl. case) and `plate_t` (the real plywood thickness) in `stand.scad`.

| Export | Command |
|---|---|
| Both brackets, laid out for printing | `openscad -o stand_print.stl -D 'part="print"' stand.scad` |
| Plate cut template | `openscad -o plate.svg -D 'part="plate2d"' stand.scad` |
| Bottom plate cut template | `openscad -o base.svg -D 'part="base2d"' stand.scad` |
| Preview | open `stand.scad` (default `part="assembly"`) |

Print the brackets lying on their outer face. They need no supports and fit side by side on the Core One bed (about 228 × 168 mm). Use PETG or PLA with 4 walls and 25 % infill.

**Hardware:** 4× M3×16 countersunk screws (DIN 7991) and 4× M3 nuts. Countersink the holes in the plate so the screw heads sit flush; the screen can then cover them. For the bottom plate: 4× M4×20 countersunk screws from below with 4× M4 nuts, which you tighten from inside the bracket window. Countersink the screws so they don't scratch the table, and add rubber feet.

**Plate:** use the SVG for the outline, the 4 bolt holes and the cable slot. Move the slot (`cable_x`, `cable_u`, `cable_w`, `cable_h`) to where the screen's HDMI/USB ports are.

**Bottom plate:** about 253 × 162 mm, the same footprint as the brackets. The SVG has the 4 bracket bolt holes and, at the back centre, the Raspberry Pi 5 hole pattern (58 × 49 mm, M2.5 standoffs). Set `pi_mount = false` to leave the Pi holes out, `pi_back` to move the Pi, and `base_margin` to make the plate larger than the brackets.
