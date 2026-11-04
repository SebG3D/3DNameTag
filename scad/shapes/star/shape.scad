// Fat five-pointed star, name across the middle, hole in the top point.
// "fit" shape: fixed outline at k=1, the backend scales it by k if needed.
R = 36;             // outer radius (tip)
inner = 0.55;       // inner radius / R
round_r = 2.5;      // corner rounding

module outline(tw, th) {
    pts = [for (i = [0:9]) let(a = 90 + i * 36, r = (i % 2 == 0) ? R : R * inner)
           [r * cos(a), r * sin(a)]];
    offset(r = round_r) offset(delta = -round_r) polygon(pts);
}

function hole_pos(tw, th) = [0, R * 0.68];
