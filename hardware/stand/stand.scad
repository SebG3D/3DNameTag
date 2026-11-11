// Angled touchscreen stand: two printed side brackets + a 6 mm plywood plate.
//
//   part = "assembly"  preview with plate and screen (not for printing)
//   part = "print"     both brackets lying flat on their outer face, no supports
//   part = "left" / "right"   one bracket in assembly orientation
//   part = "plate2d"   plate cut template (export DXF/SVG), holes + cable slot
//   part = "base2d"    bottom plate cut template: bracket bolts + Pi 5 holes
//
// The plate rests on a ledge along each bracket's sloped edge, sits against
// a front lip and is held by 2 countersunk M3 bolts per side with captive nuts
// underneath. Side walls and lip are flush with the plate top, so the screen
// can be as wide as the plate and nothing sticks up at the kids' hands.
//
// The brackets stand on a bottom plate (same plywood) and are bolted to it
// with 2 M4 bolts each; the free space between them can take a Raspberry Pi.
//
// Units mm. Assembly frame: X across, Y from front to back, Z up, Z=0 is the
// top of the bottom plate.
// Plate frame: u along the slope (up), w normal to the plate.

/* [Screen - MEASURE YOUR PANEL] */
screen_w = 240;        // outer width incl. bezel/case (placeholder for a 10.1")
screen_h = 160;        // outer height
screen_t = 12;         // thickness incl. driver board (preview only)

/* [Plate] */
angle = 30;            // tilt from the table
plate_t = 6;           // plywood/MDF thickness (measure, often 5.5-6.2)
side_margin = 2;       // plate wider than the screen, each side
bottom_margin = 12;    // plate below the screen (front edge zone)
top_margin = 8;
cable_w = 70;          // cable slot through the plate (HDMI + USB)
cable_h = 30;
cable_x = 0;           // slot centre, from the plate centre
cable_u = 0.6;         // slot centre, fraction of the plate depth from the front

/* [Bracket] */
ledge_w = 20;          // how far the ledge reaches under the plate
ledge_t = 8;           // ledge thickness under the plate
wall = 4;              // side wall outside the plate edge
lip = 6;               // front stop, along the slope
frame = 9;             // width of the frame members around the window
skin = 1;              // closes the window on the outer side (0 = open)
h0 = 14;               // plate underside height at the front edge
fit = 0.4;             // clearance plate <-> wall/lip

/* [Hardware] */
bolt_d = 3.4;          // M3 clearance
nut_af = 5.7;          // M3 nut across flats + clearance
nut_depth = 3;
bolt_u = [0.18, 0.82]; // bolt positions, fraction of the plate depth
table_hole_d = 4.5;    // M4 bolts bracket -> bottom plate (nut inside the window)

/* [Bottom plate] */
base_t = 6;            // plywood/MDF thickness
base_margin = 0;       // bottom plate larger than the brackets, each side
pi_mount = true;       // drill the Raspberry Pi 5 hole pattern (58 x 49, M2.5)
pi_hole_d = 2.7;
pi_back = 15;          // Pi board edge to the back edge of the bottom plate

part = "assembly";     // [assembly, print, left, right, plate2d, base2d]

$fn = 40;

plate_w = screen_w + 2 * side_margin;
S = screen_h + bottom_margin + top_margin;   // plate depth along the slope

function R(u, w) = [u * cos(angle) - w * sin(angle), h0 + u * sin(angle) + w * cos(angle)];

// floor line under the bracket
y_front = R(-lip - fit, -ledge_t)[0];
y_back = R(S, -ledge_t)[0];

assert(R(-lip - fit, -ledge_t)[1] >= 0, "h0 too small: the lip would go below the table");
assert(y_back - y_front < 245 && R(S, plate_t)[1] < 215, "bracket larger than the Core One bed");

// side profile in (y, z); top_w = top of the profile along the slope
module profile(top_w) {
    polygon([
        [y_front, 0],
        R(-lip - fit, -ledge_t),
        R(-lip - fit, plate_t),
        R(-fit, plate_t),
        R(-fit, top_w),
        R(S, top_w),
        R(S, -ledge_t),
        [y_back, 0],
    ]);
}

module window2d() {
    region = [[y_front, 0], R(-lip - fit, -ledge_t), R(S, -ledge_t), [y_back, 0]];
    offset(r = 6) offset(delta = -(frame + 6)) polygon(region);
}

// extrude a (y,z) profile across x in [x0, x1]
module across(x0, x1) {
    translate([x0, 0, 0]) rotate([90, 0, 90]) linear_extrude(x1 - x0) children();
}

// place something given in plate coordinates (x, u, w)
module on_plate() {
    translate([0, 0, h0]) rotate([angle, 0, 0]) children();
}

function base_bolt_x() = (fit + ledge_w - wall) / 2;   // bracket frame
function base_bolt_y() = [y_front + 0.4 * (y_back - y_front), y_back - frame - 12];

// bottom plate outline in the assembly frame
base_x0 = -wall - base_margin;
base_x1 = plate_w + 2 * fit + wall + base_margin;
base_y0 = y_front - base_margin;
base_y1 = y_back + base_margin;

// Pi 5: board 85 x 56, holes 58 x 49, 3.5 from one short and both long edges
pi_board = [85, 56];
pi_origin = [(base_x0 + base_x1) / 2 - pi_board[0] / 2, base_y1 - pi_back - pi_board[1]];
pi_holes = [for (dx = [3.5, 61.5], dy = [3.5, 52.5]) pi_origin + [dx, dy]];

function bolt_x() = fit + ledge_w / 2;     // from the plate's outer edge, bracket frame

// left bracket; plate edge at x = 0 (plus fit), plate extends to +x
module bracket() {
    difference() {
        union() {
            across(-wall, 0) profile(plate_t);           // side wall, flush with plate top
            across(0, fit + ledge_w) profile(0);          // ledge under the plate
        }
        across(-wall + skin, fit + ledge_w + 1) window2d();   // open towards the inside
        for (f = bolt_u) on_plate() translate([bolt_x(), f * S, 0]) {
            translate([0, 0, -ledge_t - 1]) cylinder(d = bolt_d, h = ledge_t + 2);
            // captive nut from below, a vertex points along x (= print up)
            translate([0, 0, -ledge_t - 1]) cylinder(d = nut_af / cos(30), h = nut_depth + 1, $fn = 6);
        }
        // bolts into the bottom plate, inside the window so the nut is reachable
        for (y = base_bolt_y())
            translate([base_bolt_x(), y, -1]) cylinder(d = table_hole_d, h = frame + 2);
    }
}

module right_bracket() {
    translate([plate_w + 2 * fit, 0, 0]) mirror([1, 0, 0]) bracket();
}

module flat() rotate([0, -90, 0]) translate([wall, 0, 0]) bracket();

module plate2d() {
    difference() {
        square([plate_w, S]);
        for (x = [bolt_x() - fit, plate_w - bolt_x() + fit], f = bolt_u)
            translate([x, f * S]) circle(d = 3.4);
        translate([plate_w / 2 + cable_x, cable_u * S]) offset(r = 5) offset(delta = -5)
            square([cable_w, cable_h], center = true);
    }
}

module base2d() {
    difference() {
        translate([base_x0, base_y0]) square([base_x1 - base_x0, base_y1 - base_y0]);
        for (y = base_bolt_y(), x = [base_bolt_x(), plate_w + 2 * fit - base_bolt_x()])
            translate([x, y]) circle(d = table_hole_d);
        if (pi_mount) for (h = pi_holes) translate(h) circle(d = pi_hole_d);
    }
}

if (part == "left") bracket();
else if (part == "right") right_bracket();
else if (part == "print") {
    // outer face on the bed, side by side; the right one is the mirror image
    flat();
    translate([10, 0, 0]) mirror([1, 0, 0]) flat();
}
else if (part == "plate2d") plate2d();
else if (part == "base2d") translate([-base_x0, -base_y0]) base2d();   // origin at a corner
else {
    color("orange") bracket();
    color("orange") right_bracket();
    color("burlywood") translate([0, 0, -base_t]) linear_extrude(base_t) base2d();
    if (pi_mount) color("green") translate([pi_origin[0], pi_origin[1], 5]) cube([pi_board[0], pi_board[1], 1.6]);
    on_plate() translate([fit, 0, 0]) {
        color("burlywood") linear_extrude(plate_t) plate2d();
        color("#333") translate([side_margin, bottom_margin, plate_t]) cube([screen_w, screen_h, screen_t]);
    }
}
