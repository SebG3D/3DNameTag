// Christmas bell, tall and slim for a vertical name; dome, flared lip,
// clapper, hanger ring with the hole. "fit" shape.
dome_r = 14;        // top dome
dome_y = 50;
lip_w = 50;         // width at the lip
lip_y = 10;         // lip bottom
lip_t = 5;          // lip thickness (rounded ends)
waist_w = 30;       // width at the waist (y = waist_y), gives the bell curve
waist_y = 34;
clapper_r = 5.5;
ring_r = 5.5;
ring_y = dome_y + dome_r + 2.5;

module outline(tw, th) {
    union() {
        hull() {
            translate([0, dome_y]) circle(r = dome_r);
            translate([-waist_w / 2, waist_y]) square([waist_w, 1]);
        }
        hull() {
            translate([-waist_w / 2, waist_y]) square([waist_w, 1]);
            translate([-lip_w / 2 + lip_t / 2, lip_y + lip_t / 2]) circle(d = lip_t);
            translate([lip_w / 2 - lip_t / 2, lip_y + lip_t / 2]) circle(d = lip_t);
        }
        translate([0, lip_y]) circle(r = clapper_r);
        translate([0, ring_y]) circle(r = ring_r);
    }
}

function hole_pos(tw, th) = [0, ring_y];
