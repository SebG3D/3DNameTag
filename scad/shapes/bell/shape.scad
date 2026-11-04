// Christmas bell: dome, flared lip, clapper, hanger ring with the hole.
// "fit" shape. Name across the wide lower part.
dome_r = 17;        // top dome
dome_y = 40;
lip_w = 64;         // width at the lip
lip_y = 10;         // lip bottom
lip_t = 5;          // lip thickness (straight part)
clapper_r = 6;
ring_r = 5.5;
ring_y = dome_y + dome_r + 3;

module outline(tw, th) {
    union() {
        hull() {
            translate([0, dome_y]) circle(r = dome_r);
            translate([-lip_w / 2 + lip_t / 2, lip_y + lip_t / 2]) circle(d = lip_t);
            translate([lip_w / 2 - lip_t / 2, lip_y + lip_t / 2]) circle(d = lip_t);
        }
        translate([0, lip_y]) circle(r = clapper_r);
        translate([0, ring_y]) circle(r = ring_r);
    }
}

function hole_pos(tw, th) = [0, ring_y];
