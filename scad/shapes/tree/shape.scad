// Christmas tree: three trapezoid tiers, trunk, ring on top for the hole.
// "fit" shape. Name across the bottom (widest) tier.
tiers = [   // [y_bottom, y_top, half width bottom, half width top]
    [8, 34, 36, 15],
    [28, 52, 27, 10],
    [46, 68, 19, 4],
];
trunk = [14, 9];        // width, height (below the first tier)
ring_r = 5.5;           // ring on the top for the hole
ring_y = 71;

module outline(tw, th) {
    offset(r = 1.5) offset(delta = -1.5) union() {
        for (t = tiers)
            polygon([[-t[2], t[0]], [t[2], t[0]], [t[3], t[1]], [-t[3], t[1]]]);
        translate([-trunk[0] / 2, 8 - trunk[1] - 0.01]) square([trunk[0], trunk[1] + 0.02]);
        translate([0, ring_y]) circle(r = ring_r);
        translate([-3, 60]) square([6, ring_y - 60]);
    }
}

function hole_pos(tw, th) = [0, ring_y];
