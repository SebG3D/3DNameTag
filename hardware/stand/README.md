# Touchscreen stand

Two printed side brackets plus an 8 mm plywood plate, tilted 30°, standing on a plywood bottom plate. The space between the brackets has room for the Pi.

Sized for the **Waveshare 13.3inch HDMI LCD (H)** (glass front 324.57 × 202.97 mm, LCD panel and electronics bonded to its back). The panel drops through a cutout in the plate, and the glass rim rests on top of the plate on the screen's own double-sided tape. No other mounting is needed. The cutout is 6 mm smaller than the glass at the top, left and right, and 10 mm smaller at the bottom (front edge).

| Plate | Size |
|---|---|
| Plate outline | 356.6 × 223 mm |
| Cutout | 312.57 × 186.97 mm, 3 mm corner radius |
| Cutout position | 22 mm from the left/right edges, 22 mm from the front edge, 14 mm from the back edge |
| Glass position (on top) | 16 mm from the left/right edges, 12 mm from the front edge, 8 mm from the back edge |
| Bottom plate | about 366 × 199 mm |

**Before cutting:** `plate_t` and `base_t` are set to 8 mm (measured plywood). Measure `screen_t`, the depth behind the glass including the electronics; it only affects the preview and the check that the panel clears the bottom plate.

| Export | Command |
|---|---|
| Left bracket, ready to print (one per job) | `openscad -o stand_left.stl -D 'part="print_left"' stand.scad` |
| Right bracket | `openscad -o stand_right.stl -D 'part="print_right"' stand.scad` |
| Plate cut template | `openscad -o plate.svg -D 'part="plate2d"' stand.scad` |
| Bottom plate cut template | `openscad -o base.svg -D 'part="base2d"' stand.scad` |
| Preview | open `stand.scad` (default `part="assembly"`) |

Print the brackets lying on their outer face, one per print job (each is about 207 × 132 mm, so two don't fit on the bed). They need no supports. Use PETG or PLA with 4 walls and 25 % infill. With PETG, one bracket takes about 3 h and 113 g on a 0.4 nozzle (roughly twice as long on the 0.25).

**Hardware:** 4× M3×15 countersunk screws (DIN 7991) and 4× M3 nuts hold the plate. With the 8 mm plate the screw reaches 7 mm below the plate and goes fully through the nut (nut at 3–5.4 mm). The plate rests on the ledge along each bracket's sloped edge, against the front lip, with the side walls flush with its top. Each nut slides into a slot that opens on the bracket's inner face, just below the ledge surface. Push it in until it lines up with the hole, then drive the screw from the top. The holes sit 10 mm from the plate's side edges and 40.1 mm and 182.8 mm from its front edge. Countersink them so the screw heads sit flush. For the bottom plate: 4 more M3×15 countersunk screws from below with 4 M3 nuts (8 M3×15 and 8 M3 nuts in total). Each nut drops into a hex pocket in the bracket's bottom frame from inside the window. The pocket holds the nut, so you only turn the screw from below. The pocket floor is 3 mm, so the screw goes through 11 mm and is fully engaged in the nut. Countersink the screws so they don't scratch the table, and add rubber feet.

**Plate:** use the SVG/DXF for the outline, the 4 bolt holes and the screen cutout. Check that the panel behind the glass really fits through the cutout before cutting, and make the edges of the cutout neat; they stay hidden under the glass. The countersunk bolt heads sit next to the glass and stay visible but flush. The cables leave from the back of the panel, under the plate.

**Bottom plate:** about 253 × 162 mm, the same footprint as the brackets. The SVG has the 4 bracket bolt holes and, at the back centre, the Raspberry Pi 5 hole pattern (58 × 49 mm, M2.5 standoffs). Set `pi_mount = false` to leave the Pi holes out, `pi_back` to move the Pi, and `base_margin` to make the plate larger than the brackets.
