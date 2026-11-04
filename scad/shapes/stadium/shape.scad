// Classic key tag: rounded bar that grows with the name, hole on the left.
// "grow" shape: outline(tw, th) gets the text bbox (centred at origin).
pad_x = 4;          // text to end of the bar (right side)
pad_y = 4;          // text to top/bottom edge
min_h = 20;         // minimum bar height
min_len = 50;       // minimum overall length (short names)
hole_space = 9;     // extra length on the left for the hole
hole_wall = 3;      // material between hole and left edge

function bar_h(th) = max(min_h, th + 2 * pad_y);
function body_w(tw) = max(tw + 2 * pad_x, min_len - hole_space);   // text part, centred
function bar_left(tw) = -body_w(tw) / 2 - hole_space;
function bar_right(tw) = body_w(tw) / 2;

module outline(tw, th) {
    r = bar_h(th) / 2;
    hull() {
        translate([bar_left(tw) + r, 0]) circle(r = r);
        translate([max(bar_right(tw) - r, bar_left(tw) + r), 0]) circle(r = r);
    }
}

function hole_pos(tw, th) = [bar_left(tw) + hole_wall + 4.5 / 2, 0];
